from collections.abc import Callable
from typing import Optional


class ProgressStep:
    """Context manager for a single progress step."""
    
    def __init__(self, reporter: 'ProgressReporter', weight: float, message: str):
        self.reporter = reporter
        self.weight = weight
        self.message = message
        self.step_progress = 0.0
        
    def __enter__(self):
        self.reporter._start_step(self.weight, self.message)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.reporter._complete_step()
        
    def increment(self, amount: float = 1.0, message: Optional[str] = None):
        """
        Increment progress within this step.
        
        Args:
            amount: Amount to increment (typically 1.0 for each item processed)
            message: Optional message to report with this increment
        """
        self.step_progress += amount
        # Calculate progress as percentage of this step's weight
        step_percentage = min(1.0, self.step_progress / self.weight) if self.weight > 0 else 1.0
        self.reporter._update_current_step(step_percentage, message or self.message)


class ProgressReporter:
    """
    A robust progress reporter using context managers for steps.
    
    Usage:
        reporter = ProgressReporter(callback)
        with reporter.step(10, "Authenticating..."):
            # do auth work
        with reporter.step(len(files), "Processing files...") as step:
            for i, file in enumerate(files):
                # process file
                step.increment(1, f"Processing {file['name']}")
    """

    def __init__(self, callback: Callable[[float, str], None] | None = None):
        self._callback = callback
        self._total_weight = 0.0
        self._completed_weight = 0.0
        self._current_step_weight = 0.0
        self._current_step_progress = 0.0

    def step(self, weight: float, message: str) -> ProgressStep:
        """
        Create a progress step context manager.
        
        Args:
            weight: Relative weight of this step (e.g., number of items to process)
            message: Message to display when starting this step
            
        Returns:
            ProgressStep context manager
        """
        return ProgressStep(self, weight, message)

    def _start_step(self, weight: float, message: str):
        """Internal method to start a new step."""
        self._total_weight += weight
        self._current_step_weight = weight
        self._current_step_progress = 0.0
        self._report_progress(message)

    def _update_current_step(self, step_percentage: float, message: str):
        """Internal method to update progress within the current step."""
        self._current_step_progress = step_percentage
        self._report_progress(message)

    def _complete_step(self):
        """Internal method to complete the current step."""
        self._completed_weight += self._current_step_weight
        self._current_step_weight = 0.0
        self._current_step_progress = 0.0

    def _report_progress(self, message: str):
        """Internal method to calculate and report overall progress."""
        if self._total_weight == 0:
            percentage = 0.0
        else:
            # Calculate overall progress as:
            # (completed steps + current step progress) / total weight
            current_progress = self._completed_weight + (self._current_step_weight * self._current_step_progress)
            percentage = current_progress / self._total_weight
        
        if self._callback:
            self._callback(percentage, message)
