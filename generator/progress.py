

class ProgressReporter:
    """
    A helper class to report progress.

    Attributes:
        total_progress (int): The total progress value.
        callback (Callable[[float, str], None] | None): A callback function to report progress.
        current_progress (int): The current progress value.
    """

    def __init__(self, total_progress: int, callback: Callable[[float, str], None] | None = None):
        """
        Initialize the ProgressReporter.

        Args:
            total_progress (int): The total progress value.
            callback (Callable[[float, str], None] | None): A callback function to report progress.
        """
        self.total_progress = total_progress
        self.callback = callback
        self.current_progress = 0

    def increment_progress(self, increment: int, message: str):
        """
        Increment the progress and call the callback with the updated percentage and message.

        Args:
            increment (int): The value to increment the progress by.
            message (str): A message to include in the callback.
        """
        self.current_progress += increment
        percentage = (self.current_progress / self.total_progress) * 100
        if self.callback:
            self.callback(percentage, message)
