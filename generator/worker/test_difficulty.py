import pytest

from .difficulty import assign_difficulty_bins
from .models import File


def test_assign_difficulty_bins_empty_list():
    """Test that an empty list of files is handled correctly."""
    files = []
    assign_difficulty_bins(files)
    assert files == []


def test_assign_difficulty_bins_no_valid_difficulties():
    """Test that files without difficulty properties are all assigned bin 0."""
    files = [
        File(id="1", name="A"),
        File(id="2", name="B", properties={"difficulty": ""}),
        File(id="3", name="C", properties={"difficulty": "invalid"}),
    ]
    assign_difficulty_bins(files)
    for file in files:
        assert file.properties["difficulty_bin"] == "0"


def test_assign_difficulty_bins_simple_distribution():
    """Test a simple linear distribution of difficulties."""
    files = [
        File(id="1", name="A", properties={"difficulty": "1.0"}),  # min -> bin 1
        File(id="2", name="B", properties={"difficulty": "2.0"}),
        File(id="3", name="C", properties={"difficulty": "3.0"}),
        File(id="4", name="D", properties={"difficulty": "4.0"}),
        File(id="5", name="E", properties={"difficulty": "5.0"}),
    ]
    assign_difficulty_bins(files)
    bins = [f.properties["difficulty_bin"] for f in files]
    assert bins == ["1", "2", "3", "4", "5"]


def test_assign_difficulty_bins_with_missing_values():
    """Test that missing or invalid values are handled correctly."""
    files = [
        File(id="1", name="A", properties={"difficulty": "1.0"}),
        File(id="2", name="B"),  # No difficulty property -> bin 0
        File(id="3", name="C", properties={"difficulty": "5.0"}),
    ]
    assign_difficulty_bins(files)
    bins = [f.properties["difficulty_bin"] for f in files]
    assert bins == ["1", "0", "5"]


def test_assign_difficulty_bins_clamping():
    """Test that bins are clamped correctly."""
    # Min is 2. Scaler is 5-2=3.
    # 2.0 -> (0.0) -> bin 1
    # 3.5 -> (1.5 / 3 = 0.5) -> bin 3
    # 5.0 -> (3.0 / 3 = 1.0) -> bin 5
    # 6.0 -> (4.0 / 3 = 1.33) -> bin 5 (clamped)
    files = [
        File(id="1", name="A", properties={"difficulty": "2.0"}),
        File(id="2", name="B", properties={"difficulty": "3.5"}),
        File(id="3", name="C", properties={"difficulty": "5.0"}),
        File(id="4", name="D", properties={"difficulty": "6.0"}),
    ]
    assign_difficulty_bins(files)
    bins = [f.properties["difficulty_bin"] for f in files]
    assert bins == ["1", "3", "5", "5"]


def test_assign_difficulty_bins_custom_bin_count():
    """Test with a different number of bins."""
    files = [
        File(id="1", name="A", properties={"difficulty": "1.0"}),
        File(id="2", name="B", properties={"difficulty": "3.0"}),
        File(id="3", name="C", properties={"difficulty": "5.0"}),
    ]
    # Bins for 3: [0, 0.33, 0.66, 1.0]
    # 1.0 -> 0.0 -> bin 1
    # 3.0 -> 0.5 -> bin 2
    # 5.0 -> 1.0 -> bin 3
    assign_difficulty_bins(files, num_bins=3)
    bins = [f.properties["difficulty_bin"] for f in files]
    assert bins == ["1", "2", "3"]
