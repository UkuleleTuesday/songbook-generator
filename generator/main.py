# Expose Cloud Function entry points from sub-packages.
# This file allows functions-framework to discover the decorated functions.

from .api.main import api_main
from .worker.main import worker_main
from .merger.main import merger_main

# Make linters happy
__all__ = ["api_main", "worker_main", "merger_main"]
