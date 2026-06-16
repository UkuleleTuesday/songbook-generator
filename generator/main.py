import functions_framework

# Import the actual function handlers from sub-packages
from .api.main import api_main
from .worker.main import worker_main
from .cache_updater.main import cache_updater_main
from .drivewatcher.main import drivewatcher_main
from .drivewatcher.watch import drivewatch_main
from .drivewebhook.main import drivewebhook_main
from .tagupdater.main import tagupdater_main


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


@functions_framework.cloud_event
def cache_updater(cloud_event):
    """CloudEvent Function for the cache updating service."""
    return cache_updater_main(cloud_event)


@functions_framework.cloud_event
def drivewatcher(cloud_event):
    """CloudEvent Function for Drive change detection (push-based consumer)."""
    return drivewatcher_main(cloud_event)


@functions_framework.cloud_event
def drivewatch(cloud_event):
    """CloudEvent Function for Drive watch channel management (renewal)."""
    return drivewatch_main(cloud_event)


@functions_framework.http
def drivewebhook(request):
    """HTTP Cloud Function for receiving Google Drive push notifications."""
    return drivewebhook_main(request)


@functions_framework.cloud_event
def tagupdater(cloud_event):
    """CloudEvent Function for updating Google Drive file tags."""
    return tagupdater_main(cloud_event)
