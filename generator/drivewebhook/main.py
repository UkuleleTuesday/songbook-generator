"""
Google Drive webhook receiver.

This module provides an HTTP endpoint that receives push notifications
from the Google Drive changes.watch API, validates the channel token,
and forwards a compact event to a Pub/Sub topic for downstream processing.
"""

import hmac
import json
import os
from functools import lru_cache

import click
from flask import Request
from google.api_core.exceptions import GoogleAPICallError
from google.auth import default
from google.cloud import pubsub_v1

from ..common.tracing import get_tracer, setup_tracing


@lru_cache(maxsize=1)
def _get_services() -> dict:
    """Initialize services for the Drive webhook receiver."""
    _, project_id = default()
    if project_id:
        os.environ["GCP_PROJECT_ID"] = project_id
        if "GOOGLE_CLOUD_PROJECT" not in os.environ:
            os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

    service_name = os.environ.get("K_SERVICE", "songbook-drivewebhook")
    setup_tracing(service_name)
    tracer = get_tracer(__name__)

    publisher = pubsub_v1.PublisherClient()
    webhook_topic = os.environ.get(
        "DRIVE_WEBHOOK_PUBSUB_TOPIC", "drive-webhook-notifications"
    )
    topic_path = publisher.topic_path(project_id, webhook_topic)

    return {
        "tracer": tracer,
        "publisher": publisher,
        "topic_path": topic_path,
        "project_id": project_id,
    }


def _validate_token(channel_token: str, verify_token: str) -> bool:
    """Validate the channel token using constant-time comparison."""
    return hmac.compare_digest(channel_token, verify_token)


def drivewebhook_main(request: Request):
    """
    HTTP Cloud Function entry point for Google Drive push notifications.

    Validates the X-Goog-Channel-Token header, extracts notification
    metadata, publishes a compact payload to Pub/Sub, and returns 204.
    """
    services = _get_services()
    verify_token = os.environ.get("VERIFY_TOKEN", "")

    channel_token = request.headers.get("X-Goog-Channel-Token", "")
    if not _validate_token(channel_token, verify_token):
        click.echo("Rejected: invalid channel token", err=True)
        return "", 403

    resource_state = request.headers.get("X-Goog-Resource-State", "")
    channel_id = request.headers.get("X-Goog-Channel-Id", "")
    resource_id = request.headers.get("X-Goog-Resource-Id", "")
    message_number = request.headers.get("X-Goog-Message-Number", "0")

    click.echo(
        f"Drive notification received: state={resource_state}, "
        f"channel={channel_id}, message={message_number}"
    )

    with services["tracer"].start_as_current_span("drivewebhook_publish") as span:
        span.set_attribute("resource_state", resource_state)
        span.set_attribute("channel_id", channel_id)
        span.set_attribute("message_number", message_number)

        payload = {
            "channel_id": channel_id,
            "resource_id": resource_id,
            "resource_state": resource_state,
            "message_number": message_number,
        }

        try:
            future = services["publisher"].publish(
                services["topic_path"],
                json.dumps(payload).encode("utf-8"),
                channel_id=channel_id,
                resource_state=resource_state,
                message_number=message_number,
            )
            future.result()
            span.set_attribute("published", True)
            click.echo(f"Published webhook notification for channel {channel_id}")
        except GoogleAPICallError as e:
            click.echo(f"Failed to publish notification: {e}", err=True)
            span.set_attribute("error", str(e))
            return "", 500

    return "", 204
