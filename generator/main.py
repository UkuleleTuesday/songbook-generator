import os
import json
import base64
import tempfile
from pdf import generate_songbook
import functions_framework
from google.cloud import firestore, storage
from flask import abort
import traceback
from filters import FilterParser, PropertyFilter, FilterGroup
from typing import Union, Optional

# Initialized at cold start
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
FIRESTORE_COLLECTION = os.environ["FIRESTORE_COLLECTION"]
GCS_CDN_BUCKET = os.environ["GCS_CDN_BUCKET"]
GCS_WORKER_CACHE_BUCKET = os.environ["GCS_WORKER_CACHE_BUCKET"]

db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
cdn_bucket = storage_client.bucket(GCS_CDN_BUCKET)
cache_bucket = storage_client.bucket(GCS_WORKER_CACHE_BUCKET)


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

    job_ref = db.collection(FIRESTORE_COLLECTION).document(job_id)

    # 2) Mark RUNNING
    print(f"Marking job {job_id} as RUNNING in Firestore")
    job_ref.update({"status": "RUNNING", "started_at": firestore.SERVER_TIMESTAMP})

    try:
        source_folders = params["source_folders"]
        cover_file_id = params.get("cover_file_id")
        limit = params.get("limit")
        
        # Parse filters parameter
        filters_param = params.get("filters")
        client_filter = None
        if filters_param:
            try:
                client_filter = parse_filters(filters_param)
                print(f"Parsed client filter: {client_filter}")
            except Exception as e:
                print(f"Error parsing filters: {e}")
                job_ref.update(
                    {
                        "status": "FAILED",
                        "completed_at": firestore.SERVER_TIMESTAMP,
                        "error": f"Invalid filter format: {str(e)}",
                    }
                )
                return

        # 3) Generate into a temp file
        out_path = tempfile.mktemp(suffix=".pdf")
        print(f"Generating songbook for job {job_id} with parameters: {params}")

        # Create progress callback and pass it to generate_songbook
        progress_callback = make_progress_callback(job_ref)
        generate_songbook(
            source_folders, out_path, limit, cover_file_id, client_filter, progress_callback
        )

        # 4) Upload to GCS
        blob = cdn_bucket.blob(f"{job_id}/songbook.pdf")
        print(f"Uploading generated songbook to GCS bucket: {GCS_CDN_BUCKET}")
        blob.upload_from_filename(out_path, content_type="application/pdf")
        result_url = blob.public_url  # or use signed URL if you need auth

        # 5) Update Firestore to COMPLETED
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
    except Exception:
        # on any failure, mark FAILED
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
