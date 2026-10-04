#!/usr/bin/env python3
"""Summarise GCS access logs: egress, operations, and what drives them.

The songbooks bucket writes usage logs to ``ukulele-tuesday-songbooks-logs``
(configured in ``deploy-gcs.sh``). Each ``…_usage_…`` object is an hourly CSV of
requests with ``sc_bytes`` served per request, which is the only per-object
egress data available without a BigQuery billing export (#394).

This reports volumes, not cost, and it only sees the public songbooks bucket —
writes to the CDN and cache buckets are not logged here, which is why class A
operations read as zero.

Usage:
    uv run python scripts/analyze_access_logs.py --days 30
    uv run python scripts/analyze_access_logs.py --days 7 --top 20
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import click
from google.cloud import storage

DEFAULT_LOGS_BUCKET = "ukulele-tuesday-songbooks-logs"

# Usage log objects are named <bucket>_usage_<YYYY>_<MM>_<DD>_<HH>_…; storage
# logs (<bucket>_storage_…) are daily size snapshots and carry no requests.
USAGE_NAME = re.compile(r"_usage_(\d{4})_(\d{2})_(\d{2})_")

# Operations are billed in two tiers. Anything that writes or lists is Class A,
# reads are Class B. https://cloud.google.com/storage/pricing#operations-pricing
CLASS_A_PREFIXES = ("PUT", "POST", "LIST", "PATCH", "DELETE", "COPY", "COMPOSE")

# No cost estimates here on purpose. List prices do not describe what is
# actually billed — the billing export shows worldwide download at €0.00 for
# this account, so multiplying bytes by a list price overstates egress by its
# entire value. Read volumes from this script, read cost from the billing
# export grouped by SKU.

BOT_PATTERN = re.compile(
    r"bot|crawl|spider|slurp|facebookexternalhit|preview|monitoring|curl|wget|python-requests",
    re.IGNORECASE,
)


@dataclass
class Totals:
    requests: int = 0
    egress_bytes: int = 0
    class_a: int = 0
    class_b: int = 0
    by_object: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_agent: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    bot_bytes: int = 0
    bot_requests: int = 0
    status: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _log_date(name: str) -> Optional[datetime]:
    m = USAGE_NAME.search(name)
    if not m:
        return None
    year, month, day = (int(g) for g in m.groups())
    return datetime(year, month, day, tzinfo=timezone.utc)


def _agent_label(user_agent: str) -> str:
    """Collapse a user agent to something countable."""
    if not user_agent:
        return "(none)"
    for marker in ("GoogleOther", "Googlebot", "bingbot", "AhrefsBot", "SemrushBot"):
        if marker.lower() in user_agent.lower():
            return marker
    if BOT_PATTERN.search(user_agent):
        return "other bot"
    for browser in ("Chrome", "Safari", "Firefox", "Edge"):
        if browser in user_agent:
            return browser
    return user_agent[:40]


def accumulate(blob_text: str, totals: Totals) -> None:
    reader = csv.DictReader(io.StringIO(blob_text))
    for row in reader:
        operation = row.get("cs_operation") or ""
        if not operation:
            continue
        totals.requests += 1
        sc_bytes = int(row.get("sc_bytes") or 0)
        totals.egress_bytes += sc_bytes
        totals.status[row.get("sc_status") or "?"] += 1

        if operation.startswith(CLASS_A_PREFIXES):
            totals.class_a += 1
        else:
            totals.class_b += 1

        obj = row.get("cs_object") or "(bucket-level)"
        totals.by_object[obj] += sc_bytes

        agent = _agent_label(row.get("cs_user_agent") or "")
        totals.by_agent[agent] += sc_bytes
        if agent != "(none)" and (
            agent in {"GoogleOther", "Googlebot", "bingbot", "AhrefsBot", "SemrushBot"}
            or agent == "other bot"
        ):
            totals.bot_bytes += sc_bytes
            totals.bot_requests += 1


def _gb(n: int) -> float:
    return n / 1_000_000_000


@click.command()
@click.option("--bucket", default=DEFAULT_LOGS_BUCKET, help="Logs bucket to read.")
@click.option("--days", default=30, help="How many days back to include.")
@click.option("--top", default=15, help="How many top objects to show.")
@click.option("--project", default=None, help="GCP project (defaults to ADC).")
def main(bucket: str, days: int, top: int, project: Optional[str]) -> None:
    """Summarise egress and operations from GCS usage logs."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    client = storage.Client(project=project) if project else storage.Client()

    # The bucket holds tens of thousands of objects, so list one date prefix at
    # a time rather than scanning everything and filtering client-side.
    totals = Totals()
    logs_read = 0
    for offset in range(days + 1):
        day = (datetime.now(timezone.utc) - timedelta(days=offset)).strftime("%Y_%m_%d")
        prefix = f"{bucket.removesuffix('-logs')}_usage_{day}"
        for blob in client.list_blobs(bucket, prefix=prefix):
            date = _log_date(blob.name)
            if date is None or date < cutoff:
                continue
            accumulate(blob.download_as_text(), totals)
            logs_read += 1

    if not logs_read:
        click.echo(f"No usage logs in the last {days} days.", err=True)
        return

    click.echo(f"\n{logs_read} usage logs, last {days} days\n")
    click.echo(f"  requests       {totals.requests:,}")
    click.echo(f"  egress         {_gb(totals.egress_bytes):.2f} GB")
    click.echo(
        f"  operations     {totals.class_a:,} class A + {totals.class_b:,} class B"
    )
    if totals.requests:
        share = 100 * totals.bot_bytes / max(totals.egress_bytes, 1)
        click.echo(
            f"  bot traffic    {totals.bot_requests:,} requests, "
            f"{_gb(totals.bot_bytes):.2f} GB ({share:.0f}% of egress)"
        )

    click.echo(
        "\n  status codes: "
        + ", ".join(
            f"{k}×{v:,}"
            for k, v in sorted(totals.status.items(), key=lambda kv: -kv[1])
        )
    )

    click.echo(f"\n  top {top} objects by egress:")
    for obj, byts in sorted(totals.by_object.items(), key=lambda kv: -kv[1])[:top]:
        click.echo(f"    {_gb(byts):8.2f} GB  {obj}")

    click.echo("\n  egress by client:")
    for agent, byts in sorted(totals.by_agent.items(), key=lambda kv: -kv[1])[:10]:
        click.echo(f"    {_gb(byts):8.2f} GB  {agent}")
    click.echo()


if __name__ == "__main__":
    main()
