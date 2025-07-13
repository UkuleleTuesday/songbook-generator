import os
import json
import base64
import tempfile
import functions_framework
from google.cloud import firestore, storage
from flask import abort
import traceback
from filters import FilterParser, PropertyFilter, FilterGroup
from typing import Union, Optional

from pdf import generate_songbook, init_services

# Initialize tracing
from common.tracing import setup_tracing, get_tracer

# Initialized at cold start
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
FIRESTORE_COLLECTION = os.environ["FIRESTORE_COLLECTION"]
GCS_CDN_BUCKET = os.environ["GCS_CDN_BUCKET"]
GCS_WORKER_CACHE_BUCKET = os.environ["GCS_WORKER_CACHE_BUCKET"]

# Set up tracing
setup_tracing("songbook-generator")

db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
cdn_bucket = storage_client.bucket(GCS_CDN_BUCKET)
cache_bucket = storage_client.bucket(GCS_WORKER_CACHE_BUCKET)

# Initialize tracer
tracer = get_tracer(__name__)


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


@functions_framework.cloud_event
def main(cloud_event):
    with tracer.start_as_current_span("worker_main") as main_span:
        # 1) Decode Pub/Sub message
        print("Received Cloud Event with data:", cloud_event.data)
        envelope = cloud_event.data
        if "message" not in envelope:
            abort(400, "No Pub/Sub message received")
        print("Extracting Pub/Sub message from envelope")
        msg = envelope["message"]

        data_payload = base64.b64decode(msg["data"]).decode("utf-8")
        print("Decoding and parsing Pub/Sub message payload")
        evt = json.loads(data_payload)

        print(f"Received event: {evt}")
        job_id = evt["job_id"]
        params = evt["params"]

        main_span.set_attribute("job_id", job_id)
        main_span.set_attribute("params_size", len(json.dumps(params)))

        job_ref = db.collection(FIRESTORE_COLLECTION).document(job_id)

        # 2) Mark RUNNING
        with tracer.start_as_current_span("update_job_status") as status_span:
            print(f"Marking job {job_id} as RUNNING in Firestore")
            job_ref.update(
                {"status": "RUNNING", "started_at": firestore.SERVER_TIMESTAMP}
            )
            status_span.set_attribute("status", "RUNNING")

        try:
            drive, cache = init_services()
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
                with tracer.start_as_current_span("parse_filters") as filter_span:
                    try:
                        client_filter = parse_filters(filters_param)
                        print(f"Parsed client filter: {client_filter}")
                        filter_span.set_attribute("has_filters", True)
                        filter_span.set_attribute(
                            "filter_type", type(client_filter).__name__
                        )
                    except Exception as e:
                        print(f"Error parsing filters: {e}")
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
            with tracer.start_as_current_span("generate_songbook") as gen_span:
                out_path = tempfile.mktemp(suffix=".pdf")
                print(f"Generating songbook for job {job_id} with parameters: {params}")
                if preface_file_ids:
                    print(f"Using {len(preface_file_ids)} preface files")
                if postface_file_ids:
                    print(f"Using {len(postface_file_ids)} postface files")

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
                gen_span.set_attribute("output_path", out_path)

            # 4) Upload to GCS
            with tracer.start_as_current_span("upload_to_gcs") as upload_span:
                blob = cdn_bucket.blob(f"{job_id}/songbook.pdf")
                print(f"Uploading generated songbook to GCS bucket: {GCS_CDN_BUCKET}")
                blob.upload_from_filename(out_path, content_type="application/pdf")
                result_url = blob.public_url  # or use signed URL if you need auth
                upload_span.set_attribute("gcs_bucket", GCS_CDN_BUCKET)
                upload_span.set_attribute("blob_name", f"{job_id}/songbook.pdf")

            # 5) Update Firestore to COMPLETED
            with tracer.start_as_current_span("complete_job") as complete_span:
                print(
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

        except Exception as e:
            # on any failure, mark FAILED
            main_span.set_attribute("error", str(e))
            main_span.set_attribute("status", "FAILED")

            job_ref.update(
                {
                    "status": "FAILED",
                    "completed_at": firestore.SERVER_TIMESTAMP,
                    "error": "Internal error during songbook generation",
                }
            )
            print(f"Job failed: {job_id}")
            print("Error details:")
            print(traceback.format_exc())
