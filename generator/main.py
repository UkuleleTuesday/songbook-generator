# Central entry points for different services (API, Worker, Merger).
# This file is used by functions-framework to route requests to the correct service.
import functions_framework

# Each entrypoint imports and calls the main function from its respective module.
# The main functions within those modules are responsible for handling the specific
# request or event.


@functions_framework.http
def api(request):
    """HTTP Cloud Function for the API service."""
    from api.main import api_main

    return api_main(request)


@functions_framework.cloud_event
def worker(cloud_event):
    """CloudEvent Function for the songbook generation worker."""
    from worker.main import worker_main

    return worker_main(cloud_event)


@functions_framework.http
def merger(request):
    """HTTP Cloud Function for the PDF merging service."""
    from merger.main import merger_main

    return merger_main(request)
