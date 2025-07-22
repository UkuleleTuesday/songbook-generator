from typing import List

import numpy as np

from .models import File


def assign_difficulty_bins(files: List[File], num_bins: int = 5) -> None:
    """
    Calculate and assign a difficulty bin to each file based on its 'difficulty'
    property. The logic is ported from the original UTDocxMerger.py script.

    The difficulty values are normalized relative to each other and then
    distributed into a specified number of bins. The result is stored back
    in each file's `properties` dictionary under the key 'difficulty_bin'.

    Args:
        files: A list of File objects to process.
        num_bins: The number of difficulty bins to use.
    """
    if not files:
        return

    raw_difficulties = []
    for f in files:
        try:
            raw_difficulties.append(float(f.properties.get("difficulty", -1)))
        except (ValueError, TypeError):
            raw_difficulties.append(-1)

    diffs = np.array(raw_difficulties)
    valid_mask = diffs != -1

    if not np.any(valid_mask):
        for file in files:
            file.properties["difficulty_bin"] = "0"
        return

    min_diff = diffs[valid_mask].min()
    # The original script used a hardcoded max of 5.
    scaler = 5.0 - min_diff
    if scaler <= 0:
        scaler = 1.0  # Avoid division by zero if all difficulties are >= 5

    # Normalize valid difficulties to a 0-1 range
    diffs[valid_mask] = (diffs[valid_mask] - min_diff) / scaler

    # Digitize into bins. Bins are 1-based, e.g., for num_bins=5, [1, 2, 3, 4, 5]
    bins = np.linspace(0, 1, num_bins + 1)
    digitized = np.digitize(diffs[valid_mask], bins=bins, right=True)

    # Clamp values to be within [1, num_bins]
    digitized[digitized == 0] = 1
    digitized[digitized > num_bins] = num_bins
    diffs[valid_mask] = digitized

    # Assign the calculated bin back to the file properties
    for i, file in enumerate(files):
        bin_index = int(diffs[i])
        file.properties["difficulty_bin"] = str(bin_index)
