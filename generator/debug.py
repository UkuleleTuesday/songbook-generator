import os
import psutil

proc = psutil.Process(os.getpid())


def log_resource_usage():
    mem = proc.memory_info().rss / 1024**2
    fds = proc.num_fds()
    print(f"RSS: {mem:.1f}MB | FDs: {fds}")
