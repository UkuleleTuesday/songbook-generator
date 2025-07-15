# Central entry points for different services (API, Worker, Merger).
# This file is used by functions-framework to route requests to the correct service.
import functions_framework
from .common.tracing import setup_tracing


def _init_tracing(service_name: str):
    """Initialize tracing for the given service."""
    setup_tracing(service_name)


@functions_framework.http
def api(request):
    """HTTP Cloud Function for the API service."""
    _init_tracing("songbook-api")
    from .api.main import api_main

    return api_main(request)


@functions_framework.cloud_event
def worker(cloud_event):
    """CloudEvent Function for the songbook generation worker."""
    _init_tracing("songbook-generator")
    from .worker.main import worker_main

    return worker_main(cloud_event)


@functions_framework.http
def merger(request):
    """HTTP Cloud Function for the PDF merging service."""
    _init_tracing("songbook-merger")
    from .merger.main import merger_main

    return merger_main(request)
