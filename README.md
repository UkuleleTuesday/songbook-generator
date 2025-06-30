# Songbook Generator for Ukulele Tuesday

## Overview

Songbook Generator is a web app accessible at
[https://jjst.github.io/songbook-generator/](https://jjst.github.io/songbook-generator/). It allows users to generate a
song book, collating song sheets + a cover stored on google drive.

## Features

- **Web Interface**: User-friendly web app for generating songbooks.
- **Google Drive Integration**: Authenticate and query files from a Google Drive folder.
- **PDF Merging**: Combine multiple PDFs into a single master PDF.
- **Table of Contents**: Automatically generate a table of contents for the merged PDF.
- **Cover Generation**: Dynamically generate a cover page using a Google Doc template, with placeholders replaced by real data.

## Usage

Visit the web app at [https://jjst.github.io/songbook-generator/](https://jjst.github.io/songbook-generator/). Use the
interface to specify advanced settings like Folder ID, Cover File ID, and Limit, then click "Generate PDF" to create
your songbook.

## Development

### Requirements
- Python 3.12+
- [gcloud](https://cloud.google.com/sdk/docs/install) CLI installed for authentication

### Authentication
Before running the backend, authenticate with Google Cloud using the following command:
```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/cloud-platform
```

### Running the generator locally

The easiest way to run the generator locally is to use `functions-framework`.

```
uv run functions-framework --source generator --target main --debug
```

### Configuration
The backend uses a configuration file located at:
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

Note: a lot of these are vestigial remains from when the tool was mainly runnable as a standalone executable -- support
for this may disappear...

### Caching
The backend uses a caching mechanism to store downloaded files and generated covers locally. Cached files are stored in:
```bash
~/.cache/songbook-generator/cache
```
Subdirectories include:
- `song-sheets`: Cached song sheet PDFs.
- `covers`: Cached cover PDFs.

### Testing

Run tests locally via:
```bash
uv run pytest
```
