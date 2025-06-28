# Songbook Generator for Ukulele Tuesday

## Overview

Songbook Generator is a Python-based CLI tool designed specifically for Ukulele Tuesday. It creates a master PDF from files stored in a specified Google Drive folder. The tool authenticates with Google Drive, downloads files as PDFs, merges them into a single document, and adds a table of contents.

## Features

- **Google Drive Integration**: Authenticate and query files from a Google Drive folder.
- **PDF Download**: Download files as PDFs, with caching to avoid redundant downloads.
- **PDF Merging**: Combine multiple PDFs into a single master PDF.
- **Table of Contents**: Automatically generate a table of contents for the merged PDF.
- **Cover Generation**: Dynamically generate a cover page using a Google Doc template, with placeholders replaced by real data.
- **Caching**: Efficient caching mechanism to store downloaded files and generated covers locally, reducing redundant API calls.
- **Configurable Settings**: Use a TOML configuration file to specify folder IDs, fonts, and other settings.

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for development and building. Ensure `uv` is installed on your system (check the link above for instructions).

Clone the repository:
```bash
git clone <repository-url>
cd <repository-directory>
```

## Usage

Run the CLI tool with the following options:

```bash
uv run songbook-generator [--source-folder <FOLDER_ID>] [--limit <LIMIT>]
```

### Options:
- `--source-folder` or `-s`: The Google Drive folder ID to read files from (optional, defaults to current song sheets
    folder).
- `--limit` or `-l`: Limit the number of files to process (optional).

This should just work, though:

```bash
uv run songbook-generator 
```

### Output Example
To see what the generated output looks like, check the [`SAMPLE.pdf`](SAMPLE.pdf) file included in the repository.

## Development

### Requirements
- Python 3.12+
- `uv` for dependency management and running the project
- `gcloud` CLI installed for authentication

### Authentication
Before running the tool, authenticate with Google Cloud using the following command:
```bash
gcloud auth application-default login --client-id-file=client-secret.json --scopes=https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/cloud-platform
```

**Note**: The app is currently whitelisted for test users only. If you are not already whitelisted, please contact the project owner to request access.

### Configuration
The tool uses a configuration file located at:
```bash
~/.config/songbook-generator/config.toml
```
This file allows you to specify folder IDs, fonts, and other settings. Example structure:
```toml
[song-sheets]
folder-ids = ["<DEFAULT_FOLDER_ID>"]

[cover]
file-id = "<COVER_TEMPLATE_FILE_ID>"

[toc]
font = "/usr/share/fonts/truetype/msttcorefonts/Verdana.ttf"
fontsize = 9
title-font = "/usr/share/fonts/truetype/msttcorefonts/Verdana.ttf"
title-fontsize = 16
```

### Caching
The tool uses a caching mechanism to store downloaded files and generated covers locally. Cached files are stored in:
```bash
~/.cache/songbook-generator/cache
```
Subdirectories include:
- `song-sheets`: Cached song sheet PDFs.
- `covers`: Cached cover PDFs.

### Testing
Run the pre-commit tests:
```bash
uv run songbook-generator -s 1b_ZuZVOGgvkKVSUypkbRwBsXLVQGjl95 -l 3
```
