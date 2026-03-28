# Songbook Generator for Ukulele Tuesday

## Overview

Songbook Generator is a web app accessible at
[https://ukuleletuesday.github.io/songbook-generator/](https://ukuleletuesday.github.io/songbook-generator/). It allows users to generate a
song book based on a series of configurable parameters.

## Features

- **Web Interface**: User-friendly web app for generating songbooks with asynchronous job processing.
- **Google Drive Integration**: Authenticate and query files from a Google Drive folder.
- **PDF Merging**: Combine multiple PDFs into a single master PDF.
- **Table of Contents**: Automatically generate a table of contents for the merged PDF.
- **Cover Generation**: Dynamically generate a cover page using a Google Doc template, with placeholders replaced by real data.
- **Async Processing**: Jobs are queued and processed asynchronously with real-time progress updates.

## Usage

Visit the web app at [https://ukuleletuesday.github.io/songbook-generator/](https://ukuleletuesday.github.io/songbook-generator/). Use the
interface to tweak which songs get included, and tweak the advanced parameters if you feel adventurous. Then click "Generate PDF" to create
your songbook. The app will show progress updates and provide a download link when complete.

## Architecture

The application uses a microservices architecture deployed on Google Cloud:

- **Frontend**: Static web app (`ui/`) hosted on GitHub Pages, built with [Material Design Lite](https://getmdl.io/).
- **API Service** (`generator/api/main.py`): Handles job creation, queues work via Pub/Sub, and tracks job status in Firestore.
- **Worker Service** (`generator/worker/main.py`): Processes PDF generation jobs asynchronously.
- **Cache Updater Service** (`generator/cache_updater/main.py`): Periodically syncs song data and metadata from Google Drive to a GCS cache bucket (this way, the worker has very little work to do).
- **Tag Updater Service** (`generator/tagupdater/main.py`): Processes individual file change events from Google Drive to update tags and metadata. This service is triggered by the Drive Watcher and ensures tags are kept up-to-date without causing timeouts. Supports LLM-backed tag enrichment (year, duration, genre) via Gemini — enabled by default, disabled with `TAGUPDATER_LLM_TAGGING_ENABLED=false`.
- **Drive Watcher Service** (`generator/drivewatcher/main.py`): Monitors Google Drive for file changes and publishes change events to trigger the Tag Updater and cache refresh operations.
- **CLI Tool** (`generator/cli/`): A standalone command-line interface for local development, testing, and utilities.
  It exposes the features of both the worker and cache updater (downloading and syncing song sheets, and generating a
  songbook) so they're easy to test locally.

## Wanna help?

While this is a workable proof of concept, there are still a fair amount of limitations. Help report issues, suggest enhancements -- or if you're a coder, roll up your sleeves and help improve this :-)

Dev instructions are below. Check out [issues](https://github.com/ukuleletuesday/songbook-generator/issues) for good first issues for inspiration on what to help out with.

## Development

### Requirements

#### git

Install [Git](https://git-scm.com/downloads) on your system.

Clone this repository to your local environment.

#### uv (Project packaging)

The project uses [uv](https://docs.astral.sh/uv/) for Python package management. Follow the install instructions for your system.

#### Google Cloud CLI (Infrastructure, authentication)

Install the [gcloud](https://cloud.google.com/sdk/docs/install) CLI for authentication.

#### Python

The code is written in and uses Python 3.12+, use [uv to install Python 3.12 if needed](https://docs.astral.sh/uv/guides/install-python/).

```sh
uv python install
```

Should tell uv to install the latest Python version.

### Authentication

To run the application locally against live Google Cloud services, you need to
authenticate. This project uses service account impersonation, which allows you
to run code locally with the permissions of a service account.

First, ask an existing project admin to grant your Google account the `Service
Account User` role on the `songbook-generator` service account.

**Note:** members of dev@ukuleletuesday.ie should have permissions by default.

Once you have permission, authenticate by running the following command:

```bash
gcloud auth application-default login
```

### Code Quality and Pre-commit Hooks

This repository uses pre-commit hooks to maintain code quality and consistency. The hooks run automatically on every commit and include:

- **ruff**: Python linting for code quality issues
- **ruff-format**: Python code formatting
- **pytest**: Run the test suite
- **Various file checks**: Check for trailing whitespace, end of files, Python AST validation, etc.

#### Setting up pre-commit hooks

To set up pre-commit hooks locally:

```bash
# Install dependencies (includes pre-commit)
uv sync

# Install the pre-commit hooks
uvx pre-commit install
```

#### Running pre-commit hooks manually

You can run all hooks manually on all files:

```bash
uvx pre-commit run --all-files
```

Or run specific hooks:

```bash
uvx ruff check .
uvx ruff format .
uv run pytest
```

#### Fixing formatting issues

If the `ruff-format` hook fails, you may need to run the formatter manually to fix the issues:

```bash
uvx ruff format
```

This will automatically format your code according to the project's style guidelines. After running this command, stage and commit the formatted files.

### Local Development with CLI

The easiest way to test the PDF generation functionality locally is to use the CLI. This approach leverages a pre-existing cache of PDF songsheets stored in GCS, which makes local generation much faster as it doesn't require hitting the Google Drive API for every file.

```bash
# Install dependencies
uv sync

# Download the GCS cache to your local machine. This is used by the 'generate' command.
uv run songbook-tools cache download

# Run the generator (will output to ./out/songbook.pdf by default)
uv run songbook-tools generate
```

Run `uv run songbook-tools --help` for more commands and options.

### CLI Commands

The `songbook-tools` CLI provides commands for local development and utility tasks,
organised into groups (`cache`, `songs`, `editions`, `specialbooks`, `tags`) and
standalone commands (`generate`, `merge-pdfs`, `validate-pdf`, `print-settings`).

Run `uv run songbook-tools --help` for a full list of commands and groups, and
`uv run songbook-tools <command> --help` (or `uv run songbook-tools <group> <subcommand> --help`)
for detailed options on any individual command.

### Testing Full Application

For testing the complete web application including the asynchronous job processing:

1. **Pull Request Preview Environments**: Every PR automatically deploys a complete preview environment with all components (frontend, API, and worker services). This is the recommended way to test the full application flow.

2. **Cloud Functions Development**: While you can run individual Cloud Functions locally using `functions-framework`, we typically test by pushing changes and using the preview environments rather than running the full stack locally.

### Configuration

#### Local CLI Configuration

The CLI uses a configuration file located at:

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

It's definitely not complete at this stage though and doesn't expose all possible config options.

#### Cloud Functions Environment

The Cloud Functions require these environment variables:

- `GCP_PROJECT_ID`: Google Cloud Project ID
- `FIRESTORE_COLLECTION`: Firestore collection name for job tracking
- `GCS_CDN_BUCKET`: Storage bucket for generated PDFs
- `GCS_WORKER_CACHE_BUCKET`: Storage bucket for caching intermediate files
- `PUBSUB_TOPIC`: Pub/Sub topic for job queue

... and probably a bunch more. Check `.env` for the full list.

**Tag Updater specific variables:**

- `TAGUPDATER_TRIGGER_FIELD`: Only write metadata when the value of this field changes (e.g. `status`).
- `TAGUPDATER_DRY_RUN`: Set to `true` to compute tags without writing back to Drive. Automatically set on PR preview deployments.
- `TAGUPDATER_LLM_TAGGING_ENABLED`: Set to `false` to disable LLM-backed tags (year, duration, genre via Gemini + Google Search). Enabled by default.

### Caching

The backend uses a caching mechanism to store downloaded files and generated covers locally. Supported caching implementations are the local file system when running locally, and GCS when running on the cloud. Locally, cached files are stored in:

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

## Deployment

### Google Cloud Setup

The application requires several GCP services. Use the provided script to set up all necessary resources:

```bash
# Set up required environment variables (see deploy-gcs.sh for full list)
export GCP_PROJECT_ID="your-project-id"
export GCP_REGION="us-central1"
# ... other variables

# Run the setup script
./deploy-gcs.sh
```

`.env` contains good defaults, excluding necessary exports for credential files you will need for interacting with Google services.

This script will:

- Enable required APIs (Pub/Sub, Firestore, Storage, Eventarc)
- Create Pub/Sub topics
- Initialize Firestore database
- Create GCS buckets with appropriate permissions
- Set up IAM roles and lifecycle policies

### Application Deployment

The application is deployed via GitHub Actions on pushes to main and pull requests. Manual deployment can be done using gcloud commands (see the GitHub Actions workflow for details).

### Songbook Editions

Each songbook edition is defined by a single YAML file in `generator/config/songbooks/`. The filename (without extension) is the edition ID used everywhere else in the system (API, CLI, workflows). All `.yaml` files in that directory are loaded automatically — no code changes are needed to add or remove an edition.

Each config file describes what songs to include (via tag-based filters), which Google Drive files to use for the cover and any preface pages, and optional table of contents customisations. See the existing files in `generator/config/songbooks/` for concrete examples.

Run `uv run songbook-tools editions list` to see all currently configured editions (both YAML-based and any discovered drive-based editions).

**Adding or updating an edition**

1. Add or edit a file in `generator/config/songbooks/`.
2. Open a pull request — CI will automatically generate a preview PDF for the affected edition(s) and post a download link in the PR comments.
3. Merge the PR — the updated PDF is published to GCS and the edition is immediately available.

**Removing an edition**

Delete its YAML file and open a pull request. No other changes are needed.

#### Experimental: Drive-Based Edition Support

As an alternative to YAML config files, editions can be configured directly in Google Drive. Each Drive-based edition is a Google Drive folder containing a `.songbook.yaml` file (same schema as above). Setting `use_folder_components: true` in that YAML resolves cover, preface, postface, and song files from named subfolders (`Cover/`, `Preface/`, `Postface/`, `Songs/`) rather than explicit Drive file IDs.

**Shortcuts to folders** inside any of these component subfolders (e.g. `Songs/`) are resolved recursively: the generator follows the shortcut, lists the contents of the target folder, and includes those files exactly as if they had been placed directly in the subfolder. This makes it easy to link an entire external folder of songs into an edition without copying each file individually. Multiple levels of nested shortcuts are supported; circular references are detected and skipped automatically.

Drive editions are discovered by scanning folders listed in `GDRIVE_SONGBOOK_EDITIONS_FOLDER_IDS` (comma-separated). Drive editions are referenced by their Drive folder ID. Run `uv run songbook-tools editions list` to see all discovered editions and their IDs.

### Automated Songbook Generation

Songbooks are generated by GitHub Actions workflows. The main workflow is `.github/workflows/generate-songbook.yaml`, which is a reusable workflow that can generate any songbook edition.

For example, `.github/workflows/tuesday-songbook-cronjob.yaml` uses this reusable workflow to generate the "current" songbook every Tuesday.

**Workflow Triggers**

Workflows can be triggered in three ways:

1.  **Scheduled**: Some workflows run on a schedule (e.g., weekly) to automatically update specific songbooks.
2.  **Config change**: Editing a file in `generator/config/songbooks/` automatically triggers a regeneration of the affected edition(s). On a pull request this generates a preview PDF available as a workflow artifact (never published to the public bucket). On merge to `main` the updated PDF is published.
3.  **Manual (`workflow_dispatch`)**: You can trigger the `generate-songbook` workflow manually from the "Actions" tab in the GitHub repository. You will need to specify which edition to generate.

**Workflow Logic**

When triggered, the `generate-songbook` workflow:
1.  Calls the API service to start the asynchronous generation process for the specified edition.
2.  Polls the API until the job is complete.
3.  Downloads the generated PDF and validates its contents.
4.  If running on the `main` branch, it uploads the final PDF to a public GCS bucket.

## Observability

### Logging

Access logs at https://console.cloud.google.com/ under `Monitoring` > `Logs explorer`

### Traces

Access traces at https://console.cloud.google.com/ under `Monitoring` > `Trace explorer`
