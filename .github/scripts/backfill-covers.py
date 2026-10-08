#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "google-cloud-storage>=2.16",
#   "pymupdf>=1.26.1",
# ]
# ///
"""Backfill cover images for songbooks published before covers existed.

Usage:
    backfill-covers.py <bucket> [--dry-run]

For each edition in <bucket> whose latest.json has no cover_filename, renders
the published PDF's first page (as `songbook-tools render-cover` does), uploads
it as <pdf_basename>.cover.png and adds cover_filename, title and subject to
latest.json. Nothing else in latest.json changes — in particular generated_at,
so backfilled books don't look freshly updated on the songbooks site — and no
book is regenerated or republished.

latest.json is only rewritten if it is still the version that was read, so a
publish landing mid-run is never overwritten.
"""

import json
import sys
from pathlib import Path

import fitz  # PyMuPDF
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage

CACHE_CONTROL_LATEST = "public, max-age=60"
CACHE_CONTROL_COVER = "public, max-age=300"
COVER_DPI = 150


def list_editions(client, bucket) -> list[str]:
    iterator = client.list_blobs(bucket, delimiter="/")
    prefixes = set()
    for page in iterator.pages:
        prefixes.update(page.prefixes)
    return sorted(p.rstrip("/") for p in prefixes)


def render_cover(pdf_bytes: bytes) -> tuple[bytes, str, str]:
    """Return (cover PNG, title, subject) for a PDF."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        png = pdf.load_page(0).get_pixmap(dpi=COVER_DPI, alpha=True).tobytes("png")
        meta = pdf.metadata or {}
        return png, meta.get("title") or "", meta.get("subject") or ""


def backfill_edition(bucket, edition: str, dry_run: bool) -> str:
    latest_blob = bucket.get_blob(f"{edition}/latest.json")
    if latest_blob is None:
        return "no latest.json, skipped"
    latest = json.loads(latest_blob.download_as_text())
    pdf_filename = latest.get("pdf_filename")
    if not pdf_filename:
        return "no pdf_filename, skipped"
    if latest.get("cover_filename"):
        return "already has a cover"

    cover_filename = pdf_filename.removesuffix(".pdf") + ".cover.png"
    if dry_run:
        return f"would add {cover_filename}"

    pdf_bytes = bucket.blob(f"{edition}/{pdf_filename}").download_as_bytes()
    png, title, subject = render_cover(pdf_bytes)

    cover_blob = bucket.blob(f"{edition}/{cover_filename}")
    cover_blob.cache_control = CACHE_CONTROL_COVER
    cover_blob.upload_from_string(png, content_type="image/png")

    latest.update(cover_filename=cover_filename, title=title, subject=subject)
    out = bucket.blob(f"{edition}/latest.json")
    out.cache_control = CACHE_CONTROL_LATEST
    try:
        out.upload_from_string(
            json.dumps(latest),
            content_type="application/json",
            if_generation_match=latest_blob.generation,
        )
    except PreconditionFailed:
        return "latest.json changed during backfill (republished?), left alone"
    return f"added {cover_filename}"


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv[1:]
    if len(args) != 1:
        print(f"Usage: {Path(sys.argv[0]).name} <bucket> [--dry-run]", file=sys.stderr)
        sys.exit(1)

    client = storage.Client()
    bucket = client.bucket(args[0])
    failures = 0
    for edition in list_editions(client, bucket):
        try:
            outcome = backfill_edition(bucket, edition, dry_run)
        except Exception as e:  # noqa: BLE001 - report and keep backfilling the rest
            outcome = f"FAILED: {e}"
            failures += 1
        print(f"{edition}: {outcome}")

    if failures:
        sys.exit(1)
    print("✅ Dry run complete" if dry_run else "✅ Covers backfilled")


if __name__ == "__main__":
    main()
