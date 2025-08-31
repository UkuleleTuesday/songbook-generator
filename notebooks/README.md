# Analysis Notebooks

This directory contains Jupyter notebooks for exploring and analyzing various aspects of the songbook generator.

## Available Notebooks

### `difficulty_binning_analysis.ipynb`

**Purpose**: Explore and visualize the difficulty binning logic used in the songbook generator.

**What it does**:
- Analyzes the current relative binning algorithm from `generator/worker/difficulty.py`
- Demonstrates how the same songs get different bin assignments depending on the song collection
- Compares relative vs. absolute binning approaches
- Identifies edge cases and inconsistencies
- Provides interactive widgets for exploring parameter effects
- Can fetch real song data from Google Drive (requires proper authentication)

**Key findings**:
- The current algorithm uses relative binning, making results unpredictable for users
- Same songs can be assigned different difficulty bins depending on what other songs are included
- Adding very hard songs changes bin assignments for all existing songs
- Several edge cases cause unexpected behavior

**Requirements**:
- Jupyter, matplotlib, seaborn, pandas (installed in dev dependencies)
- For real data analysis: Google Cloud credentials configured

**Usage**:
```bash
# Start Jupyter
uv run jupyter notebook

# Or use JupyterLab
uv run jupyter lab
```

Then open `difficulty_binning_analysis.ipynb` and run the cells.

**Related to**: Issue #121 (difficulty grading system improvements)

---

## Adding New Notebooks

When creating new analysis notebooks:

1. Follow the same structure with proper markdown documentation
2. Include helper functions for reusability
3. Test with both sample and real data when applicable
4. Provide clear findings and recommendations
5. Update this README with a description of the new notebook
