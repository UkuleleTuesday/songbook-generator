# Expose Cloud Function entry points from sub-packages.
# This file allows functions-framework to discover the decorated functions.

from .api.main import api_main as api
from .worker.main import worker_main as worker
from .merger.main import merger_main as merger

# Make linters happy
__all__ = ["api", "worker", "merger"]
