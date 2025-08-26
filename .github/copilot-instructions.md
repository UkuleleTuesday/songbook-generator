# Copilot Instructions for Songbook Generator

## Repository Overview

**Songbook Generator** is a Python application for creating PDF songbooks for "Ukulele Tuesday" sessions. It pulls song sheets from Google Drive, generates covers and tables of contents, and creates customized PDF songbooks. The system is deployed as Google Cloud Functions with a static HTML UI.

**Key characteristics:**
- **Language:** Python 3.12+ 
- **Package Manager:** uv (modern Python package manager)
- **Architecture:** Microservices on Google Cloud Platform
- **Size:** ~45 Python files, ~3,800+ lines of code
- **Domain:** PDF generation, Google Drive integration, web services

## Essential Build & Test Commands

**ALWAYS run these commands in the exact order specified:**

### 1. Initial Setup (Required First)
```bash
# Install dependencies - ALWAYS run first
uv sync

# This command MUST complete successfully before any other operations
```

### 2. Testing (Fast - 3-4 seconds)
```bash
# Run test suite
uv run pytest

# Run specific test file
uv run pytest generator/worker/test_pdf.py

# Expected: 137 tests should pass
```

### 3. Code Quality (Required before commits)
```bash
# Check linting (required)
ruff check .

# Check formatting (required) 
ruff format --check .

# Auto-fix formatting issues
ruff format .

# Run all pre-commit hooks manually
pre-commit run --all-files
```

### 4. CLI Tools & Validation
```bash
# Test CLI is working
uv run songbook-tools --help

# Print current configuration (useful for debugging)
uv run songbook-tools print-settings

# Manage song editions (requires file identifier)
uv run songbook-tools editions --help
```

**Important Notes:**
- **Never install packages with pip** - always use `uv sync` or `uv add`
- **Pre-commit hooks run automatically** - they include ruff, pytest, and file checks
- **Tests are co-located with code** (e.g., `test_pdf.py` next to `pdf.py`)
- **Commands timeout after 2-3 minutes** if Google Cloud credentials are missing
- **Timing expectations:** Tests run in ~1-3 seconds, uv sync takes ~30-60 seconds on first run

## Architecture & Key Directories

### Core Components (Google Cloud Functions)
- **`generator/api/`** - HTTP API endpoints (Cloud Function entry: `api`)
- **`generator/worker/`** - PDF generation worker (Cloud Function entry: `worker`) 
- **`generator/merger/`** - Google Drive sync service (Cloud Function entry: `merger`)

### Supporting Components  
- **`generator/common/`** - Shared utilities (config, caching, fonts, tracing)
- **`generator/config/`** - Configuration files (`songbooks.yaml` defines available editions)
- **`generator/cli.py`** - CLI interface (`songbook-tools` command)
- **`ui/`** - Static HTML frontend (deployed to GitHub Pages)
- **`scripts/`** - Utility scripts for maintenance tasks

### Configuration Files
- **`pyproject.toml`** - Python project configuration & dependencies
- **`.env`** - Environment variables for GCP services  
- **`generator/config/songbooks.yaml`** - Songbook edition definitions
- **`.pre-commit-config.yaml`** - Code quality hooks
- **`.github/workflows/`** - CI/CD pipelines

### Key Dependencies
- **Google Cloud:** Firestore, Pub/Sub, Storage, Cloud Functions
- **PDF Processing:** PyMuPDF, PyPDF2 (note: PyPDF2 is deprecated but still used)
- **Web Framework:** Flask (via functions-framework)
- **Config Management:** Pydantic Settings
- **Observability:** OpenTelemetry tracing

## Configuration System

The app uses a **layered configuration approach**:

1. **Default values** in Pydantic models (`generator/common/config.py`)
2. **YAML configuration** (`generator/config/songbooks.yaml`) for editions
3. **Environment variables** (`.env` file and runtime env vars)
4. **Runtime overrides** via environment variable validation

**Key environment variables needed for full functionality:**
```bash
# Google Cloud Platform
GCP_PROJECT_ID=songbook-generator
GCP_REGION=europe-west1

# Storage & Database  
FIRESTORE_COLLECTION=jobs
GCS_CDN_BUCKET=songbook-generator-cdn-europe-west1
GCS_WORKER_CACHE_BUCKET=songbook-generator-cache-europe-west1

# Google Drive
GDRIVE_SONG_SHEETS_FOLDER_IDS=folder1,folder2

# Pub/Sub
PUBSUB_TOPIC=songbook-jobs
CACHE_REFRESH_PUBSUB_TOPIC=songbook-cache-refresh-jobs
```

## GitHub Actions & CI/CD

### Workflow Overview
- **`test.yaml`** - Runs tests and linting on all PRs
- **`deploy.yaml`** - Deploys to GCP (main branch + PR previews)
- **PR Previews:** Each PR gets isolated GCP resources with `-pr-{number}` suffixes

### Deployment Process
1. **Test & Lint** - Must pass before deployment
2. **Infrastructure** - Creates Pub/Sub topics
3. **Functions** - Deploys API, Worker, and Merger Cloud Functions
4. **UI** - Deploys to GitHub Pages (main) or PR preview
5. **Cleanup** - Removes PR resources when PR is closed

### Pre-commit Hooks (Enforced)
- **ruff** - Python linting for code quality
- **ruff-format** - Python code formatting  
- **pytest** - Full test suite
- **File checks** - Trailing whitespace, EOF, AST validation
- **Security** - Gitleaks for credential scanning

## Common Issues & Workarounds

### Build Failures
**Problem:** `uv: command not found`  
**Solution:** Install uv first: `pip install uv`

**Problem:** Import errors for `generator` package  
**Solution:** Run `uv sync` to install the package in development mode

**Problem:** Tests fail with missing Google credentials  
**Solution:** Tests should pass without credentials - they use mocks

### Google Cloud Integration
**Problem:** Pre-commit hooks fail with network timeouts  
**Solution:** This is a known issue in some environments - the ruff and pytest commands work individually

**Problem:** CLI commands hang/timeout  
**Solution:** Commands requiring GCP access will timeout after 30s without credentials - this is expected

**Problem:** Missing environment variables  
**Solution:** Check `.env` file exists and contains required variables

### Code Quality
**Problem:** Pre-commit hooks fail  
**Solution:** Run `ruff format .` then `ruff check --fix .`

**Problem:** Test failures on file modifications  
**Solution:** Only fix tests that are directly related to your changes

## Testing Strategy

### Test Structure
- **Unit tests** are co-located with source files (`test_*.py`)
- **Integration tests** mock external services (Google Cloud, Google Drive)
- **137 total tests** should pass in under 5 seconds
- **No external dependencies** required for tests

### Test Categories
- **PDF Generation:** `generator/worker/test_*.py`
- **Configuration:** `generator/common/test_config.py`  
- **Google Drive:** `generator/common/test_gdrive.py`
- **Caching:** `generator/common/caching/test_*.py`
- **CLI:** `generator/test_cli.py`

### Running Tests
```bash
# All tests (recommended)
uv run pytest

# Specific test file  
uv run pytest generator/worker/test_pdf.py

# With verbose output
uv run pytest -v

# Stop on first failure
uv run pytest -x
```

## Making Code Changes

### Development Workflow
1. **Install dependencies:** `uv sync`
2. **Run tests:** `uv run pytest` (verify current state)
3. **Make changes** (keep them minimal and focused)
4. **Run tests again** (ensure no regressions)
5. **Check code quality:** `ruff check . && ruff format .`
6. **Test CLI if applicable:** `uv run songbook-tools --help`

### Code Style Conventions (ENFORCED)
- **80 character line limit** (strictly enforced)
- **Follow ruff defaults** for formatting and linting
- **No broad Exception catch-all clauses** - only catch expected exceptions
- **No trailing spaces** (automatically checked)
- **TDD approach preferred** - write tests first when possible

### Common Patterns
- **Configuration:** Use `get_settings()` to access app config
- **Caching:** Use `init_cache()` for storage abstraction  
- **Progress tracking:** Use callback pattern for long-running operations
- **Error handling:** Catch specific exceptions, log details, re-raise if needed
- **Testing:** Use pytest fixtures and mocking for external services

## CLI Tools Reference

The `songbook-tools` CLI provides several commands for development and utilities:

```bash
# Generate a songbook (requires GCP credentials)
uv run songbook-tools generate --edition current

# Download cache from GCS to local (requires credentials)
uv run songbook-tools download-cache

# Sync Google Drive to cache (requires credentials) 
uv run songbook-tools sync-cache

# Manage song editions (requires file identifier as argument)
uv run songbook-tools editions --help

# Print current configuration (works without credentials)
uv run songbook-tools print-settings
```

**Note:** Commands requiring Google Cloud or Google Drive access will timeout without proper credentials.

## Trust These Instructions

**These instructions have been validated** by running all commands and testing the workflows. When the information here conflicts with what you discover through exploration, **trust these instructions first** and only search/explore when:

1. The instructions are incomplete for your specific task
2. You encounter errors that aren't covered here  
3. You need to understand code not described here

This approach will significantly reduce the time you spend exploring and increase the likelihood of successful changes.