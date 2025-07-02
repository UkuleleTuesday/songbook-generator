from progress import ProgressReporter

def test_progress_reporter_with_callback():
    progress_updates = []

    def mock_callback(percentage, message):
        progress_updates.append((percentage, message))

    reporter = ProgressReporter(total_progress=100, callback=mock_callback)
    reporter.increment_progress(10, "Step 1")
    reporter.increment_progress(20, "Step 2")

    assert progress_updates == [
        (0.1, "Step 1"),
        (0.3, "Step 2"),
    ]

def test_progress_reporter_without_callback():
    reporter = ProgressReporter(total_progress=100, callback=None)
    reporter.increment_progress(10, "Step 1")
    reporter.increment_progress(20, "Step 2")

    # No callback, so no updates should be recorded
    assert True  # Test passes if no errors occur

def test_progress_reporter_total_progress():
    progress_updates = []

    def mock_callback(percentage, message):
        progress_updates.append((percentage, message))

    reporter = ProgressReporter(total_progress=50, callback=mock_callback)
    reporter.increment_progress(25, "Halfway")
    reporter.increment_progress(25, "Complete")

    assert progress_updates == [
        (0.5, "Halfway"),
        (1.0, "Complete"),
    ]
