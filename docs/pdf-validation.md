# PDF Validation Test Harness

This document describes the PDF validation test harness that ensures generated songbook PDFs are not corrupted or malformed before they are uploaded to the public bucket.

## Overview

The PDF validation system includes:

1. **Standalone validation script**: `scripts/validate_pdf.py`
2. **CLI command**: `songbook-tools validate-pdf`
3. **GitHub Actions integration**: Automatic validation in the build pipeline
4. **Unit tests**: Comprehensive test suite for validation functions

## Validation Checks

The validation performs the following sanity checks on generated PDFs:

### Basic Structure
- PDF file exists and is not empty
- PDF can be opened by PyMuPDF (not corrupted)
- PDF has at least one page
- First page can be accessed without errors

### Metadata Validation
- Required metadata fields are present and not empty:
  - `title`: PDF title
  - `author`: Should be "Ukulele Tuesday"
  - `creator`: Should be "Ukulele Tuesday Songbook Generator"
- Optional expected metadata validation (configurable)

### Content Validation
- Minimum page count (default: 3 pages)
- Maximum file size (default: 500MB)
- Text extraction test (ensures PDF contains readable text, not just images)

### Songbook Structure Validation
- Minimum page count for songbooks (at least 3 pages for cover + TOC + content)
- Table of Contents detection (looks for "Contents" or "Table of Contents" in first 5 pages)

## Usage

### Command Line

```bash
# Basic validation
./scripts/validate_pdf.py songbook.pdf

# Validation with expected metadata
./scripts/validate_pdf.py songbook.pdf \
  --expected-title "Ukulele Tuesday - Current Songbook" \
  --expected-author "Ukulele Tuesday" \
  --verbose

# Via CLI tool
uv run songbook-tools validate-pdf songbook.pdf --verbose

# Custom validation parameters
uv run songbook-tools validate-pdf songbook.pdf \
  --min-pages 5 \
  --max-size-mb 100 \
  --no-check-structure
```

### GitHub Actions Integration

The validation is automatically run in the `generate-songbooks.yaml` workflow:

- Runs after PDF generation but before upload to GCS
- Uses edition-specific expected titles from `songbooks.yaml`
- Fails the workflow if validation fails, preventing upload of bad PDFs
- Provides verbose output for debugging

## Exit Codes

- `0`: Validation passed
- `1`: Validation failed or error occurred

## Configuration

Default validation parameters:
- Minimum pages: 3
- Maximum file size: 500MB
- Expected author: "Ukulele Tuesday"
- Structure validation: Enabled
- Expected titles: Based on edition (from `songbooks.yaml`)

## Testing

Run the validation test suite:

```bash
uv run pytest scripts/test_validate_pdf.py -v
```

The test suite covers:
- Valid and invalid PDF files
- Missing or incorrect metadata
- File size and page count validation
- Songbook structure validation
- CLI command testing
