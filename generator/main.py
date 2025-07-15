import functions_framework

# Import the actual function handlers from sub-packages
from .api.main import api_main
from .worker.main import worker_main
from .merger.main import merger_main


# Create and decorate the entrypoints that Cloud Functions will discover.
# This makes the trigger type explicit at the entrypoint file.
@functions_framework.http
def api(request):
    """HTTP Cloud Function for the API service."""
    return api_main(request)


@functions_framework.cloud_event
def worker(cloud_event):
    """CloudEvent Function for the songbook generation worker."""
    return worker_main(cloud_event)


@functions_framework.http
def merger(request):
    """HTTP Cloud Function for the PDF merging service."""
    return merger_main(request)
