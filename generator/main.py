# Central entry points for different services (API, Worker, Merger).
# This file is used by functions-framework to route requests to the correct service.
import functions_framework
from .common.tracing import setup_tracing
import os


def _initialize():
    """Initialize common services from environment variables."""
    # These are assumed to be set in the execution environment.
    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    service_name = os.environ["SERVICE_NAME"]

    # Set other project ID env vars for consistency
    os.environ["PROJECT_ID"] = project_id
    os.environ["GCP_PROJECT_ID"] = project_id

    setup_tracing(service_name)
    return project_id, service_name


@functions_framework.http
def api(request):
    """HTTP Cloud Function for the API service."""
    _initialize()
    from .api.main import api_main

    return api_main(request)


@functions_framework.cloud_event
def worker(cloud_event):
    """CloudEvent Function for the songbook generation worker."""
    _initialize()
    from .worker.main import worker_main

    return worker_main(cloud_event)


@functions_framework.http
def merger(request):
    """HTTP Cloud Function for the PDF merging service."""
    _initialize()
    from .merger.main import merger_main

    return merger_main(request)
