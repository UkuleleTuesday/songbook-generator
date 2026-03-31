import os
import json
import base64
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from google.cloud import firestore, storage
import traceback
from loguru import logger
from opentelemetry import trace
from ..common.filters import parse_filters

from .pdf import (
    generate_songbook,
    generate_songbook_from_edition,
    load_edition_from_drive_folder,
    init_services,
    generate_manifest,
)
from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient

# Initialize tracing
from ..common.tracing import get_tracer, setup_tracing

# Cache for initialized clients to avoid re-initialization on warm starts
_services = None


def _get_services():
    """Initializes and returns services, using a cache for warm starts."""
    global _services
    if _services is not None:
        return _services

    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    service_name = os.environ.get("K_SERVICE", "songbook-generator-worker")
    os.environ["GCP_PROJECT_ID"] = project_id
    setup_tracing(service_name)
    tracer = get_tracer(__name__)

    firestore_collection = os.environ["FIRESTORE_COLLECTION"]
    gcs_cdn_bucket_name = os.environ["GCS_CDN_BUCKET"]
    db = firestore.Client(project=project_id)
    storage_client = storage.Client(project=project_id)
    cdn_bucket = storage_client.bucket(gcs_cdn_bucket_name)

    _services = {
        "tracer": tracer,
        "db": db,
        "cdn_bucket": cdn_bucket,
        "firestore_collection": firestore_collection,
        "gcs_cdn_bucket_name": gcs_cdn_bucket_name,
    }
    return _services


def make_progress_callback(job_ref):
    """Return a callback that writes progress info into Firestore."""

    def _callback(percent: float, message: str = None):
        update = {
            "status": "RUNNING",
            "progress": percent,
            "last_message": message or "",
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        job_ref.update(update)

    return _callback


def worker_main(cloud_event):
    services = _get_services()
    with services["tracer"].start_as_current_span("worker_main") as main_span:
        # 1) Decode Pub/Sub message
        logger.info(f"Received Cloud Event with data: {cloud_event.data}")
        envelope = cloud_event.data
        if "message" not in envelope:
            logger.error("No Pub/Sub message received in cloud event")
            raise ValueError("No Pub/Sub message received")
        logger.info("Extracting Pub/Sub message from envelope")
        msg = envelope["message"]

        data_payload = base64.b64decode(msg["data"]).decode("utf-8")
        logger.info("Decoding and parsing Pub/Sub message payload")
        evt = json.loads(data_payload)

        logger.info(f"Received event: {evt}")
        job_id = evt["job_id"]
        params = evt["params"]

        main_span.set_attribute("job_id", job_id)
        main_span.set_attribute("params_size", len(json.dumps(params)))

        job_ref = (
            services["db"].collection(services["firestore_collection"]).document(job_id)
        )

        # 2) Mark RUNNING
        with services["tracer"].start_as_current_span(
            "update_job_status"
        ) as status_span:
            logger.info(f"Marking job {job_id} as RUNNING in Firestore")
            job_ref.update(
                {"status": "RUNNING", "started_at": firestore.SERVER_TIMESTAMP}
            )
            status_span.set_attribute("status", "RUNNING")

        try:
            drive, cache = init_services()  # Uses ADC from env
            settings = get_settings()
            source_folders = (
                params.get("source_folders") or settings.song_sheets.folder_ids
            )
            cover_file_id = params.get("cover_file_id")
            limit = params.get("limit")
            preface_file_ids = params.get("preface_file_ids")
            postface_file_ids = params.get("postface_file_ids")

            main_span.set_attribute("source_folders_count", len(source_folders))
            if limit:
                main_span.set_attribute("limit", limit)
            if preface_file_ids:
                main_span.set_attribute("preface_files_count", len(preface_file_ids))
            if postface_file_ids:
                main_span.set_attribute("postface_files_count", len(postface_file_ids))

            # Initialize temp file paths for cleanup
            out_path_str = None
            manifest_path_str = None

            # 3) Generate into a temp file
            generation_start_time = datetime.now(timezone.utc)
            selected_edition = None
            with services["tracer"].start_as_current_span(
                "generate_songbook"
            ) as gen_span:
                out_path_str = tempfile.mktemp(suffix=".pdf")
                out_path = Path(out_path_str)
                logger.info(
                    f"Generating songbook for job {job_id} with parameters: {params}"
                )
                progress_callback = make_progress_callback(job_ref)
                edition_id = params.get("edition")

                if edition_id:
                    gen_span.set_attribute("edition_id", edition_id)
                    selected_edition = next(
                        (e for e in settings.editions if e.id == edition_id), None
                    )
                    songs_files = None
                    if not selected_edition:
                        logger.info(
                            f"Edition '{edition_id}' not found in configuration, "
                            "trying as Drive folder ID..."
                        )
                        gen_span.add_event(
                            "edition_not_in_config_trying_drive_folder",
                            {"edition_id": edition_id},
                        )
                        gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
                        try:
                            selected_edition, songs_files = (
                                load_edition_from_drive_folder(
                                    gdrive_client, edition_id
                                )
                            )
                        except ValueError as e:
                            raise ValueError(
                                f"Edition '{edition_id}' not found in configuration "
                                f"and could not be loaded from Drive: {e}"
                            ) from e
                        gen_span.set_attribute("edition.source", "drive")
                        gen_span.set_attribute("edition.drive_folder_id", edition_id)
                        gen_span.add_event(
                            "edition_resolved_from_drive",
                            {"edition_id": edition_id, "drive_folder_id": edition_id},
                        )
                    else:
                        gen_span.set_attribute("edition.source", "config")
                        if selected_edition.source_file:
                            gen_span.set_attribute(
                                "edition.config_file", selected_edition.source_file
                            )
                        gen_span.add_event(
                            "edition_resolved_from_config",
                            {
                                "edition_id": edition_id,
                                "config_file": selected_edition.source_file or "",
                            },
                        )

                    gen_span.set_attribute("edition.id", selected_edition.id)
                    gen_span.set_attribute(
                        "edition.description", selected_edition.description or ""
                    )
                    if selected_edition.filters:
                        gen_span.set_attribute(
                            "edition.filters_count", len(selected_edition.filters)
                        )
                    if songs_files is not None:
                        gen_span.set_attribute("edition.songs_pre_supplied", True)
                        gen_span.set_attribute(
                            "edition.songs_pre_supplied_count", len(songs_files)
                        )
                    logger.info(
                        f"Generating songbook for edition: {selected_edition.id} - {selected_edition.description}"
                    )
                    generation_info = generate_songbook_from_edition(
                        drive=drive,
                        cache=cache,
                        source_folders=source_folders,
                        destination_path=out_path,
                        edition=selected_edition,
                        limit=limit,
                        on_progress=progress_callback,
                        files=songs_files,
                        all_editions=settings.editions,
                    )
                else:
                    # Legacy mode: Parse filters parameter
                    filters_param = params.get("filters")
                    client_filter = None
                    if filters_param:
                        try:
                            client_filter = parse_filters(filters_param)
                        except ValueError as e:
                            raise ValueError(f"Invalid filter format: {str(e)}") from e

                    if preface_file_ids:
                        logger.info(f"Using {len(preface_file_ids)} preface files")
                    if postface_file_ids:
                        logger.info(f"Using {len(postface_file_ids)} postface files")

                    generation_info = generate_songbook(
                        drive=drive,
                        cache=cache,
                        source_folders=source_folders,
                        destination_path=out_path,
                        limit=limit,
                        cover_file_id=cover_file_id,
                        client_filter=client_filter,
                        preface_file_ids=preface_file_ids,
                        postface_file_ids=postface_file_ids,
                        on_progress=progress_callback,
                    )
                gen_span.set_attribute("output_path", str(out_path))
                generation_end_time = datetime.now(timezone.utc)
                generation_duration_seconds = (
                    generation_end_time - generation_start_time
                ).total_seconds()
                gen_span.set_attribute(
                    "generation_duration_seconds", generation_duration_seconds
                )
                gen_span.set_attribute(
                    "generated_files_count", len(generation_info.get("files", []))
                )
                gen_span.set_attribute("pdf.title", generation_info.get("title") or "")
                gen_span.set_attribute(
                    "pdf.subject", generation_info.get("subject") or ""
                )
                page_indices = generation_info.get("page_indices") or {}
                body_indices = page_indices.get("body")
                if body_indices:
                    gen_span.set_attribute(
                        "pdf.body_first_page", body_indices["first_page"]
                    )
                    gen_span.set_attribute(
                        "pdf.body_last_page", body_indices["last_page"]
                    )
                gen_span.add_event(
                    "generation_complete",
                    {
                        "files_count": len(generation_info.get("files", [])),
                        "duration_seconds": generation_duration_seconds,
                        "has_cover": page_indices.get("cover") is not None,
                        "has_preface": page_indices.get("preface") is not None,
                        "has_toc": page_indices.get("table_of_contents") is not None,
                        "has_postface": page_indices.get("postface") is not None,
                    },
                )
                logger.info(
                    f"Generation complete for job {job_id}: "
                    f"{len(generation_info.get('files', []))} files in {generation_duration_seconds:.1f}s"
                )

            # 3.5) Generate manifest.json
            with services["tracer"].start_as_current_span(
                "generate_manifest"
            ) as manifest_span:
                logger.info(f"Generating manifest for job {job_id}")
                manifest_data = generate_manifest(
                    job_id=job_id,
                    params=params,
                    destination_path=out_path,
                    files=generation_info["files"],
                    edition=selected_edition,
                    title=generation_info["title"],
                    subject=generation_info["subject"],
                    source_folders=source_folders,
                    generation_start_time=generation_start_time,
                    generation_end_time=generation_end_time,
                    page_indices=generation_info.get("page_indices"),
                )

                # Save manifest to temporary file for upload
                manifest_path_str = tempfile.mktemp(suffix=".json")
                manifest_path = Path(manifest_path_str)
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest_data, f, indent=2)

                manifest_span.set_attribute("manifest_path", str(manifest_path))
                manifest_span.set_attribute(
                    "manifest_size", os.path.getsize(manifest_path)
                )

            # 4) Upload to GCS
            with services["tracer"].start_as_current_span(
                "upload_to_gcs"
            ) as upload_span:
                blob = services["cdn_bucket"].blob(f"{job_id}/songbook.pdf")
                pdf_size_bytes = os.path.getsize(out_path_str)
                logger.info(
                    f"Uploading generated songbook to GCS bucket: {services['gcs_cdn_bucket_name']} "
                    f"(size: {pdf_size_bytes} bytes)"
                )
                blob.upload_from_filename(out_path_str, content_type="application/pdf")
                result_url = blob.public_url  # or use signed URL if you need auth
                upload_span.set_attribute("gcs_bucket", services["gcs_cdn_bucket_name"])
                upload_span.set_attribute("blob_name", f"{job_id}/songbook.pdf")
                upload_span.set_attribute("pdf_size_bytes", pdf_size_bytes)

                # Upload manifest.json alongside the PDF
                manifest_blob = services["cdn_bucket"].blob(f"{job_id}/manifest.json")
                logger.info(
                    f"Uploading generation manifest to GCS bucket: {services['gcs_cdn_bucket_name']}"
                )
                manifest_blob.upload_from_filename(
                    manifest_path_str, content_type="application/json"
                )
                manifest_url = manifest_blob.public_url
                upload_span.set_attribute(
                    "manifest_blob_name", f"{job_id}/manifest.json"
                )
                upload_span.set_attribute("manifest_url", manifest_url)

            # 5) Update Firestore to COMPLETED
            with services["tracer"].start_as_current_span(
                "complete_job"
            ) as complete_span:
                logger.info(
                    f"Marking job {job_id} as COMPLETED in Firestore with result URL: {result_url}"
                )
                job_ref.update(
                    {
                        "status": "COMPLETED",
                        "completed_at": firestore.SERVER_TIMESTAMP,
                        "result_url": result_url,
                        "manifest_url": manifest_url,
                    }
                )
                complete_span.set_attribute("status", "COMPLETED")
                complete_span.set_attribute("result_url", result_url)

        except Exception as exc:  # noqa: BLE001 - Top level error handler
            # on any failure, mark FAILED
            exc_info = traceback.format_exc()
            error_type = type(exc).__name__
            error_message = str(exc)

            main_span.set_attribute("status", "FAILED")
            main_span.set_attribute("error.type", error_type)
            main_span.set_attribute("error.message", error_message)
            main_span.set_attribute("error.stack_trace", exc_info)
            main_span.set_status(trace.StatusCode.ERROR, error_message)
            main_span.record_exception(exc)

            job_ref.update(
                {
                    "status": "FAILED",
                    "completed_at": firestore.SERVER_TIMESTAMP,
                    "error": f"{error_type}: {error_message}",
                }
            )
            logger.error(f"Job {job_id} failed with {error_type}: {error_message}")
            logger.error(f"{exc_info}")
            raise
