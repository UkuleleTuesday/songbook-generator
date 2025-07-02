from collections.abc import Callable

class ProgressReporter:
    """
    A helper class to report progress.

    Attributes:
        _total_progress (int): The total progress value.
        _callback (Callable[float, str] | None): A callback function to report progress.
        _current_progress (int): The current progress value.
    """

    def __init__(self, total_progress: int, callback: Callable[[float, str], None] | None = None):
        self._total_progress = total_progress
        self._callback = callback
        self._current_progress = 0

    def increment_progress(self, increment: int, message: str):
        """
        Increment the progress and call the callback with the updated percentage and message.

        Args:
            increment (int): The value to increment the progress by.
            message (str): A message to include in the callback.
        """
        self._current_progress += increment
        percentage = (float(self._current_progress) / float(self._total_progress))
        if self._callback:
            self._callback(percentage, message)
