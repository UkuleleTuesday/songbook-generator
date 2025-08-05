import os
import json
import base64
import tempfile
from pathlib import Path
import click
from google.cloud import firestore, storage
from flask import abort
import traceback
from ..common.filters import FilterParser, PropertyFilter, FilterGroup
from typing import Union, Optional

from .pdf import generate_songbook, init_services

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


def parse_filters(filters_param) -> Optional[Union[PropertyFilter, FilterGroup]]:
    """
    Parse the filters parameter from the API request into filter objects.

    Args:
        filters_param: Can be a string, list of strings, or dict representing filters

    Returns:
        PropertyFilter, FilterGroup, or None if no filters
    """
    if not filters_param:
        return None

    if isinstance(filters_param, str):
        # Single filter string
        return FilterParser.parse_simple_filter(filters_param)

    if isinstance(filters_param, list):
        # List of filter strings - combine with AND logic
        parsed_filters = []
        for filter_str in filters_param:
            parsed_filters.append(FilterParser.parse_simple_filter(filter_str))

        if len(parsed_filters) == 1:
            return parsed_filters[0]
        else:
            return FilterGroup(parsed_filters, "AND")

    if isinstance(filters_param, dict):
        # Complex filter object - would need more sophisticated parsing
        # For now, just handle simple cases
        if "filters" in filters_param:
            filter_list = filters_param["filters"]
            operator = filters_param.get("operator", "AND")

            parsed_filters = []
            for f in filter_list:
                if isinstance(f, str):
                    parsed_filters.append(FilterParser.parse_simple_filter(f))
                # Could handle nested filter objects here

            if len(parsed_filters) == 1:
                return parsed_filters[0]
            else:
                return FilterGroup(parsed_filters, operator)

    return None


def worker_main(cloud_event):
    services = _get_services()
    with services["tracer"].start_as_current_span("worker_main") as main_span:
        # 1) Decode Pub/Sub message
        click.echo(f"Received Cloud Event with data: {cloud_event.data}")
        envelope = cloud_event.data
        if "message" not in envelope:
            abort(400, "No Pub/Sub message received")
        click.echo("Extracting Pub/Sub message from envelope")
        msg = envelope["message"]

        data_payload = base64.b64decode(msg["data"]).decode("utf-8")
        click.echo("Decoding and parsing Pub/Sub message payload")
        evt = json.loads(data_payload)

        click.echo(f"Received event: {evt}")
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
            click.echo(f"Marking job {job_id} as RUNNING in Firestore")
            job_ref.update(
                {"status": "RUNNING", "started_at": firestore.SERVER_TIMESTAMP}
            )
            status_span.set_attribute("status", "RUNNING")

        try:
            drive, cache = init_services()  # Uses ADC from env
            source_folders = params["source_folders"]
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

            # Parse filters parameter
            filters_param = params.get("filters")
            client_filter = None
            if filters_param:
                with services["tracer"].start_as_current_span(
                    "parse_filters"
                ) as filter_span:
                    try:
                        client_filter = parse_filters(filters_param)
                        click.echo(f"Parsed client filter: {client_filter}")
                        filter_span.set_attribute("has_filters", True)
                        if client_filter:
                            filter_span.set_attribute(
                                "filter_type", type(client_filter).__name__
                            )
                    except ValueError as e:
                        click.echo(f"Error parsing filters: {e}", err=True)
                        filter_span.set_attribute("error", str(e))
                        job_ref.update(
                            {
                                "status": "FAILED",
                                "completed_at": firestore.SERVER_TIMESTAMP,
                                "error": f"Invalid filter format: {str(e)}",
                            }
                        )
                        return

            # 3) Generate into a temp file
            with services["tracer"].start_as_current_span(
                "generate_songbook"
            ) as gen_span:
                out_path_str = tempfile.mktemp(suffix=".pdf")
                out_path = Path(out_path_str)
                click.echo(
                    f"Generating songbook for job {job_id} with parameters: {params}"
                )
                if preface_file_ids:
                    click.echo(f"Using {len(preface_file_ids)} preface files")
                if postface_file_ids:
                    click.echo(f"Using {len(postface_file_ids)} postface files")

                # Create progress callback and pass it to generate_songbook
                progress_callback = make_progress_callback(job_ref)
                generate_songbook(
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

            # 4) Upload to GCS
            with services["tracer"].start_as_current_span(
                "upload_to_gcs"
            ) as upload_span:
                blob = services["cdn_bucket"].blob(f"{job_id}/songbook.pdf")
                click.echo(
                    "Uploading generated songbook to GCS bucket: "
                    f"{services['gcs_cdn_bucket_name']}"
                )
                blob.upload_from_filename(out_path_str, content_type="application/pdf")
                result_url = blob.public_url  # or use signed URL if you need auth
                upload_span.set_attribute("gcs_bucket", services["gcs_cdn_bucket_name"])
                upload_span.set_attribute("blob_name", f"{job_id}/songbook.pdf")

            # 5) Update Firestore to COMPLETED
            with services["tracer"].start_as_current_span(
                "complete_job"
            ) as complete_span:
                click.echo(
                    f"Marking job {job_id} as COMPLETED in Firestore with result URL: {result_url}"
                )
                job_ref.update(
                    {
                        "status": "COMPLETED",
                        "completed_at": firestore.SERVER_TIMESTAMP,
                        "result_url": result_url,
                    }
                )
                complete_span.set_attribute("status", "COMPLETED")
                complete_span.set_attribute("result_url", result_url)

        except Exception:  # noqa: BLE001 - Top level error handler
            # on any failure, mark FAILED
            main_span.set_attribute("status", "FAILED")

            job_ref.update(
                {
                    "status": "FAILED",
                    "completed_at": firestore.SERVER_TIMESTAMP,
                    "error": "Internal error during songbook generation",
                }
            )
            click.echo(f"Job failed: {job_id}", err=True)
            click.echo("Error details:", err=True)
            exc_info = traceback.format_exc()
            click.echo(exc_info, err=True)
            main_span.set_attribute("error.stack_trace", exc_info)
            raise
