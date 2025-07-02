from progress import ProgressReporter

def test_progress_reporter_with_callback():
    progress_updates = []

    def mock_callback(percentage, message):
        progress_updates.append((percentage, message))

    reporter = ProgressReporter(callback=mock_callback)
    
    # Test a single step
    with reporter.step(10, "Step 1") as step:
        step.increment(5, "Halfway through step 1")
        step.increment(5, "Completed step 1")
    
    # Test another step
    with reporter.step(20, "Step 2") as step:
        step.increment(10, "Halfway through step 2")
        step.increment(10, "Completed step 2")

    # Should have progress updates for each increment
    assert len(progress_updates) >= 4
    # Check that progress increases over time
    percentages = [update[0] for update in progress_updates]
    assert percentages == sorted(percentages)  # Should be non-decreasing
    # Check that final progress reaches 100%
    assert progress_updates[-1][0] == 1.0

def test_progress_reporter_without_callback():
    reporter = ProgressReporter(callback=None)
    
    # Should not raise any errors even without callback
    with reporter.step(10, "Step 1") as step:
        step.increment(5, "Halfway")
        step.increment(5, "Complete")

    # Test passes if no errors occur
    assert True

def test_progress_reporter_single_step():
    progress_updates = []

    def mock_callback(percentage, message):
        progress_updates.append((percentage, message))

    reporter = ProgressReporter(callback=mock_callback)
    
    with reporter.step(1, "Single step") as step:
        step.increment(0.5, "Halfway")
        step.increment(0.5, "Complete")

    # Should reach 100% completion
    assert progress_updates[-1][0] == 1.0
    assert "Complete" in progress_updates[-1][1]

def test_progress_reporter_multiple_steps():
    progress_updates = []

    def mock_callback(percentage, message):
        progress_updates.append((percentage, message))

    reporter = ProgressReporter(callback=mock_callback)
    
    # First step: weight 1
    with reporter.step(1, "Step 1"):
        pass
    
    # Second step: weight 2  
    with reporter.step(2, "Step 2") as step:
        step.increment(1, "Half of step 2")
        step.increment(1, "Complete step 2")
    
    # Third step: weight 1
    with reporter.step(1, "Step 3"):
        pass

    # Should have multiple progress updates
    assert len(progress_updates) > 0
    # Final progress should be 100%
    assert progress_updates[-1][0] == 1.0

def test_progress_reporter_step_increment_tracking():
    progress_updates = []

    def mock_callback(percentage, message):
        progress_updates.append((percentage, message))

    reporter = ProgressReporter(callback=mock_callback)
    
    # Single step with multiple increments
    with reporter.step(4, "Processing items") as step:
        step.increment(1, "Item 1")
        step.increment(1, "Item 2") 
        step.increment(1, "Item 3")
        step.increment(1, "Item 4")

    # Should have 5 updates: initial + 4 increments
    assert len(progress_updates) == 5
    
    # Check progression
    expected_percentages = [0.0, 0.25, 0.5, 0.75, 1.0]
    actual_percentages = [update[0] for update in progress_updates]
    
    for expected, actual in zip(expected_percentages, actual_percentages):
        assert abs(expected - actual) < 0.001  # Allow for floating point precision

def test_progress_reporter_nested_behavior():
    progress_updates = []

    def mock_callback(percentage, message):
        progress_updates.append((percentage, message))

    reporter = ProgressReporter(callback=mock_callback)
    
    # Test that steps are properly isolated
    with reporter.step(2, "First major step") as step1:
        step1.increment(1, "First increment")
        step1.increment(1, "Second increment")
    
    with reporter.step(3, "Second major step") as step2:
        step2.increment(1.5, "Halfway through second")
        step2.increment(1.5, "Completed second")

    # Should end at 100%
    assert progress_updates[-1][0] == 1.0
    
    # Should have had intermediate progress values
    percentages = [update[0] for update in progress_updates]
    assert 0.4 in [round(p, 1) for p in percentages]  # After first step (2/5 = 0.4)
