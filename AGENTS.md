# GitHub Copilot Coding Agent Guidelines

This document provides essential information about the Songbook Generator repository to help GitHub Copilot understand the codebase and contribute effectively.

## Repository Overview

The Songbook Generator is a Python application that automatically generates PDF songbooks for Ukulele Tuesday from Google Drive sources. It's built as a microservices architecture deployed on Google Cloud Platform.

### Key Components

- **Generator (`generator/`)**: Core Python package containing all business logic
- **API Service**: Flask-based REST API for songbook generation requests
- **Worker Service**: Background job processor for PDF generation
- **Cache Updater Service**: Syncs and merges song sheets from Google Drive
- **CLI Tools**: Command-line interface for local development and operations

### Architecture

The application follows a distributed architecture:
1. **API** receives generation requests and publishes jobs to Pub/Sub
2. **Worker** processes jobs asynchronously, generating PDFs and storing in GCS
3. **Cache Updater** keeps the song sheet cache up-to-date from Google Drive sources
4. **GitHub Actions** automate deployments and scheduled songbook updates

## Development Setup

### Prerequisites

- Python 3.12
- `uv` package manager (modern Python packaging tool)
- Google Cloud SDK (for cloud services interaction)
- Git for version control

### Quick Start

```bash
# Install uv package manager
pip install uv

# Install project dependencies
uv sync --locked --all-extras --dev

# Install pre-commit hooks (MANDATORY)
uvx --from 'pre-commit<5' pre-commit install

# Run tests
uv run pytest

# Run pre-commit checks (MANDATORY before any commit)
uvx --from 'pre-commit<5' pre-commit run --all-files
```

### Project Structure

```
generator/
├── api/           # Flask REST API implementation
├── cli.py         # Command-line interface entry point
├── common/        # Shared utilities and configuration
│   ├── caching/   # Local and GCS caching implementations
│   ├── config.py  # Pydantic settings management
│   ├── gdrive.py  # Google Drive integration
│   └── tracing.py # OpenTelemetry observability setup
├── cache_updater/ # Google Drive sync and PDF merging
├── worker/        # Background job processing
└── main.py        # Application entry points

.github/
├── workflows/     # CI/CD automation
└── ISSUE_TEMPLATE/ # Issue templates

scripts/           # Utility scripts for deployment and operations
ui/               # Frontend components (if applicable)
```

## Code Conventions & Patterns

### Style Guidelines (from CONVENTIONS.md)

- **Line Length**: Maximum 80 characters per line (strictly enforced)
- **Formatting**: Follow `ruff` formatter defaults
- **Linting**: Use `ruff` linter with extended rules (see `pyproject.toml`)
- **Exception Handling**: NEVER use broad `except:` or `except Exception:` clauses - only catch specific expected exceptions. This will cause exceptions to be swallowed without understanding their root cause.
- **Testing**: Follow Test-Driven Development (TDD) approach - write unit tests first whenever possible to verify your assumptions
- **Code Quality**: Keep changes small, clean and testable
- **Whitespace**: Be careful not to introduce any trailing spaces

### Pre-commit Requirements (MANDATORY)

**All commits MUST pass pre-commit hooks before being committed.** This is non-negotiable.

- **Installation**: Pre-commit hooks must be installed in the development environment: `uvx --from 'pre-commit<5' pre-commit install`
- **Validation**: Run `uvx --from 'pre-commit<5' pre-commit run --all-files` before any commit
- **Automated Checks**: Pre-commit hooks automatically run ruff formatting, linting, pytest, and other quality checks
- **No Bypassing**: Do not use `--no-verify` or similar flags to bypass pre-commit checks

### Configuration Management

The application uses Pydantic Settings for configuration:

```python
from generator.common.config import get_settings

settings = get_settings()
# Settings are loaded from environment variables and config files
```

Configuration sources (in order of precedence):
1. Environment variables
2. `~/.config/songbook-generator/config.toml` (local development)
3. `generator/config/config.toml` (defaults)

### Error Handling Pattern

```python
# ✅ Good: Specific exception handling
try:
    result = risky_operation()
except ValueError as e:
    logger.error(f"Invalid input: {e}")
    raise

# ❌ Bad: Broad exception catching
try:
    result = risky_operation()
except Exception:  # This will fail code review!
    pass
```

### Caching Pattern

The application uses a multi-tier caching system:

```python
from generator.common.caching import init_cache

# Initialize appropriate cache (local filesystem or GCS)
cache = init_cache()

# Cache operations
await cache.store("key", data)
data = await cache.retrieve("key")
```

## Testing Approach

### Test Structure

- **Unit Tests**: Located alongside source code (`test_*.py`)
- **Test Framework**: pytest with pytest-mock for mocking
- **Coverage**: Aim for high test coverage of business logic
- **Fixtures**: Use pytest fixtures for common test setup

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest generator/common/test_config.py

# Run with coverage
uv run pytest --cov=generator

# Run tests matching pattern
uv run pytest -k "test_config"
```

### Test Patterns

```python
import pytest
from generator.common import config

def test_configuration_override(monkeypatch):
    """Test environment variable override."""
    monkeypatch.setenv("SOME_SETTING", "test-value")
    config.get_settings.cache_clear()  # Clear cache for testing
    settings = config.get_settings()
    assert settings.some_setting == "test-value"
```

## Dependencies & Tools

### Core Dependencies

- **FastAPI/Flask**: Web framework for API endpoints
- **Pydantic**: Data validation and settings management
- **Google Cloud Libraries**: Firestore, Storage, Pub/Sub integration
- **PyMuPDF**: PDF manipulation and generation
- **OpenTelemetry**: Distributed tracing and observability
- **Click**: Command-line interface framework

### Development Tools

- **uv**: Fast Python package installer and resolver
- **ruff**: Python linter and formatter (replaces flake8, black, isort)
- **pytest**: Testing framework with fixtures and mocking
- **pre-commit**: Git hooks for code quality enforcement

### Google Cloud Services

- **Cloud Storage (GCS)**: PDF storage and caching
- **Firestore**: Job tracking and metadata
- **Pub/Sub**: Asynchronous job queuing
- **Cloud Trace**: Distributed tracing
- **Cloud Functions**: Serverless function hosting

## Key Implementation Details

### Asynchronous Processing

Jobs are processed asynchronously using Google Cloud Pub/Sub:

```python
# Publishing jobs
from generator.common.pubsub import publish_job

job_data = {"edition": "regular", "force": False}
await publish_job("songbook-generation", job_data)

# Processing jobs (in worker)
@trace_function("process_generation_job")
def process_job(message):
    # Job processing logic
    pass
```

### PDF Generation Pipeline

1. **Cache Sync**: Download/update song sheets from Google Drive
2. **Cover Generation**: Create custom cover pages with metadata
3. **TOC Generation**: Build table of contents with page numbers
4. **PDF Merging**: Combine all components into final songbook
5. **Upload**: Store result in public GCS bucket

### Observability

The application includes comprehensive tracing:

```python
from generator.common.tracing import get_tracer

tracer = get_tracer(__name__)

with tracer.start_as_current_span("operation_name") as span:
    span.set_attribute("custom.attribute", value)
    # Operation logic
```

## CLI Commands

The application provides several CLI tools for development and operations:

```bash
# Print current configuration
uv run songbook-tools print-settings

# Download GCS cache locally
uv run songbook-tools download-cache

# Sync from Google Drive to GCS
uv run songbook-tools sync-cache [--force]

# Generate songbook locally
uv run songbook-tools generate --edition regular --output out/

# Merge PDFs with table of contents
uv run songbook-tools merge-pdfs --output out/merged.pdf
```

## Deployment

### Environment Configuration

Key environment variables for deployment:
- `GCP_PROJECT_ID`: Google Cloud Project ID
- `GCS_*_BUCKET`: Various GCS bucket names
- `FIRESTORE_COLLECTION`: Firestore collection for job tracking
- `PUBSUB_TOPIC`: Pub/Sub topic for job queue
- `GDRIVE_*`: Google Drive folder and file IDs

### Automated Deployment

- **GitHub Actions**: Handles CI/CD pipeline
- **Preview Environments**: Every PR gets a complete preview deployment
- **Production**: Deployed on merges to main branch
- **Scheduled Jobs**: Automated songbook regeneration every 10 minutes

## Common Patterns to Follow

1. **Use type hints**: All functions should have proper type annotations
2. **Structured logging**: Use the configured logger with structured messages
3. **Configuration injection**: Use `get_settings()` for all configuration access
4. **Async/await**: Use async patterns for I/O operations
5. **Error boundaries**: Handle errors at appropriate service boundaries
6. **Tracing**: Add tracing spans for major operations

## Troubleshooting

### Common Issues

- **Missing credentials**: Ensure Google Cloud authentication is configured
- **Cache misses**: Use `download-cache` command to populate local cache
- **Build failures**: Check that all dependencies are properly locked in `uv.lock`
- **Test failures**: Clear caches with `config.get_settings.cache_clear()`

### Debug Commands

```bash
# Check current settings
uv run songbook-tools print-settings

# Validate environment setup
uv run pytest generator/common/test_config.py

# Check dependency lock file
uv lock --check
```

This repository follows modern Python development practices with strong typing, comprehensive testing, and cloud-native architecture patterns.
