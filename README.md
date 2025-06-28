# Songbook Generator for Ukulele Tuesday

## Overview

Songbook Generator is a Python-based CLI tool designed specifically for Ukulele Tuesday. It creates a master PDF from files stored in a specified Google Drive folder. The tool authenticates with Google Drive, downloads files as PDFs, merges them into a single document, and adds a table of contents.

## Features

- **Google Drive Integration**: Authenticate and query files from a Google Drive folder.
- **PDF Download**: Download files as PDFs, with caching to avoid redundant downloads.
- **PDF Merging**: Combine multiple PDFs into a single master PDF.
- **Table of Contents**: Automatically generate a table of contents for the merged PDF.

## Installation

This project uses `uv` for development and building. Ensure `uv` is installed on your system.

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

## Usage

Run the CLI tool with the following options:

```bash
uv run songbook-generator --source-folder <FOLDER_ID> --limit <LIMIT>
```

### Options:
- `--source-folder` or `-s`: The Google Drive folder ID to read files from (required).
- `--limit` or `-l`: Limit the number of files to process (optional).

Example:

```bash
uv run songbook-generator --source-folder 1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95 --limit 3
```

## Development

### Requirements
- Python 3.12+
- `uv` for dependency management and running the project

### Testing
Run the pre-commit tests:
```bash
uv run songbook-generator -s 1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95 -l 3
```
