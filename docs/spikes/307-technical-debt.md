# Spike #307 – Identify Technical Debt

**Issue:** [#307 Spike: identify technical debt](https://github.com/UkuleleTuesday/songbook-generator/issues/307)

## Problem Statement

The repository has gone through a significant number of experimentations,
iterations and changes while the system was being brought into live use for
Ukulele Tuesday.  The goal of this spike is to identify the top 5 areas of
technical debt — dead code, legacy patterns, unvalidated logic — and explain
why each area carries risk or maintenance cost.  Solutions may be included but
are not the primary focus.

---

## Findings

### 1. Deprecated CLI options that are still present in the codebase

**File:** `generator/cli.py` — `sync_cache_command`, lines 426–468

Two options — `--update-tags-only` and `--update-tags` — are still declared on
the `sync-cache` CLI command even though the functionality they controlled has
been superseded by the dedicated `tagupdater` cloud function.  They are hidden
from `--help` output (`hidden=True`) but they remain valid option names,
meaning:

- a user who passes `--update-tags` receives a warning then proceeds silently
  (the flag is ignored unless `--update-tags-only` is also present);
- `--update-tags-only` raises `click.Abort()` after printing an error —
  i.e. the CLI crashes with no useful guidance on what to do instead;
- the options still appear in `test_cli.py`, implying test coverage that exists
  only to protect dead code.

```python
# generator/cli.py:426-438 (abridged)
@click.option(
    "--update-tags-only",
    ...
    help="[DEPRECATED] This option is no longer supported. Tagging is now handled by a dedicated cloud function.",
    hidden=True,
)
@click.option(
    "--update-tags",
    ...
    help="[DEPRECATED] This option is no longer supported. Tagging is now handled by a dedicated cloud function.",
    hidden=True,
)
```

**Why it matters:** dead options carry real maintenance cost — they must be
tested, they appear in code review diffs, and they can mislead contributors
into thinking there is a CLI-driven tagging path that still works.

**Recommended action:** Remove both `--update-tags-only` and `--update-tags`
from the `sync-cache` command together with the associated guard block (lines
456–470) and any corresponding tests.

---

### 2. Dual PDF-processing libraries (PyPDF2 and PyMuPDF)

**Files:** `pyproject.toml`, `generator/cache_updater/main.py`

The project depends on *two* PDF libraries:

| Library | Version pin | Sole use site |
|---|---|---|
| `pymupdf` (fitz) | `>=1.26.1` | `worker/pdf.py`, `worker/toc.py`, `worker/cover.py`, `validation.py`, … (dozens of call sites) |
| `pypdf2` | `>=3.0.1` | `cache_updater/main.py` only — three lines |

PyPDF2 is used exclusively in `_merge_pdfs_with_toc()` to merge a list of
PDFs and count their pages:

```python
# generator/cache_updater/main.py:104-116
merger = PyPDF2.PdfMerger()
for file_info in file_metadata:
    with open(file_info["path"], "rb") as pdf_file:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        page_count = len(pdf_reader.pages)
    ...
    merger.append(file_info["path"])
merger.write(temp_merged_path)
merger.close()
```

PyMuPDF can perform exactly the same operations
(`fitz.open()` + `doc.insert_pdf()` for merging, `len(doc)` for page count)
and is already an unconditional dependency.  PyPDF2 is an extra transitive
dependency, separately versioned, separately updated, and carrying its own
CVE surface.

**Why it matters:** two libraries solving the same problem means double the
upgrade/security-patch burden, increased install size in Cloud Function
deployment packages, and risk that a future change to one merging path
diverges from the other.

**Recommended action:** Re-implement `_merge_pdfs_with_toc()` using
`fitz` (`pymupdf`) and remove the `pypdf2` dependency from `pyproject.toml`.

---

### 3. Difficulty-binning algorithm ported from legacy code without validation

**File:** `generator/worker/difficulty.py` (67 lines)

The entire `assign_difficulty_bins()` function is acknowledged as a direct
port from the original `UTDocxMerger.py` script, and is explicitly flagged for
revisiting:

```python
# generator/worker/difficulty.py:21-22
# FIXME: Logic ported from UTDocxMerger.py - needs revisiting.
# See https://github.com/UkuleleTuesday/songbook-generator/issues/121
```

Specific concerns with the current implementation:

1. **Hardcoded maximum difficulty of 5.0.** The normalization step uses
   `scaler = 5.0 - min_diff` (line 43).  If difficulty values ever exceed 5.0
   the scaler becomes negative and the bin assignments invert silently.
2. **Relative normalisation means bins are set-dependent.** Two songs with
   the same raw difficulty score can end up in different bins depending on
   what other songs are in the set being processed.  The TOC difficulty
   indicators therefore change every time the song catalogue changes.
3. **Edge-case handling is ad-hoc.** Songs with `difficulty == -1` (missing
   data) receive `bin = 0` via a special-case `int(-1.0)` conversion; songs
   with `difficulty == 5.0` are forced into `bin = num_bins` by a clamp.

A Jupyter notebook `notebooks/difficulty_binning_analysis.ipynb` already
exists, suggesting prior analysis work, but its conclusions have not yet been
reflected in a revised algorithm.

**Why it matters:** the difficulty bins drive the visual difficulty indicator
shown in the Table of Contents.  Inconsistent or surprising bin assignments
erode trust in the feature and make it harder to curate the song catalogue.

**Recommended action:** write a spike or design doc first (see issue #121);
then replace the relative normalisation with absolute thresholds (configured
in `config.toml`) and add property-based tests that exercise the edge cases
identified above.

---

### 4. Inconsistent service-initialisation patterns across cloud functions

**Files:** `generator/api/main.py` vs every other cloud-function `main.py`

All cloud functions initialise their GCP clients once and cache the result for
warm starts.  However, the API service uses a mutable global variable while
the other three services use the standard `@lru_cache(maxsize=1)` decorator:

```python
# generator/api/main.py — mutable global pattern
_services = None

def _get_services():
    global _services
    if _services is not None:
        return _services
    ...
    _services = { "tracer": tracer, "db": db, ... }
    return _services
```

```python
# generator/cache_updater/main.py — lru_cache pattern (also used by
# drivewatcher/main.py and tagupdater/main.py)
@lru_cache(maxsize=1)
def _get_services():
    ...
    return { "tracer": tracer, "cache_bucket": cache_bucket, ... }
```

The `api/main.py` module applies the same global-state pattern a second time
for `_drive_client` (lines 52–72).  Neither global is reset between tests,
which means test isolation depends on import-time side-effects rather than
explicit setup/teardown.

**Why it matters:** the inconsistency increases cognitive load for contributors
— the same problem is solved two different ways for no documented reason.  The
mutable-global pattern also makes unit-testing harder, since tests must
either monkeypatch module-level names or rely on import ordering to inject
fakes.

**Recommended action:** replace the mutable global in `api/main.py` with
`@lru_cache(maxsize=1)`, matching the pattern used everywhere else.  Update
the corresponding tests to call `_get_services.cache_clear()` in teardown
rather than setting module globals directly.

---

### 5. Hard-coded name alias in the tag updater

**File:** `generator/tagupdater/tags.py` — `tabber()`, line 303

The `tabber` tag function maps Drive file-owner display names to the
`tabber` metadata property.  A single alias is baked directly into the source
code and is acknowledged as insufficient:

```python
# generator/tagupdater/tags.py:303-305
# TODO: Replace this with a more robust aliasing system.
if name.lower() == "miguel":
    return "Mischa"
```

Adding a new alias requires a code change, a pull request, CI, and a
redeployment.  The alias list will need to grow over time as the pool of
contributors expands or as display names change (e.g. when a contributor
renames their Google account).

**Why it matters:** the current approach does not scale, and the maintenance
burden grows with every new alias needed.  The mismatch between a user's
Drive display name and the name that appears in the songbook can also go
unnoticed for an arbitrary length of time after a display-name change.

**Recommended action:** move the alias table to `generator/config.toml` (or
a dedicated section of the settings model) so that aliases can be updated via
a config-only change without touching application logic.  Example shape:

```toml
[tagging]
name_aliases = { miguel = "Mischa" }
```

---

## Summary

| # | Area | Severity | Effort to fix |
|---|---|---|---|
| 1 | Deprecated `--update-tags[-only]` CLI options | Low | Small — delete ~40 lines of code + tests |
| 2 | Dual PDF libraries (PyPDF2 + PyMuPDF) | Medium | Small — rewrite ~15 lines, remove dependency |
| 3 | Difficulty-binning algorithm ported without validation | Medium | Medium — requires analysis + algorithm redesign |
| 4 | Inconsistent service-initialisation pattern in `api/main.py` | Low | Small — swap global for `@lru_cache`, update tests |
| 5 | Hard-coded name alias in tag updater | Low | Small — move to config, add config-driven lookup |
