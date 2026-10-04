"""Compatibility imports for the shared Drive Activity API helpers."""

from generator.common.drive_activity import (
    SCOPES,
    build_activity_service,
    get_first_move_timestamp,
    get_move_events,
    normalise_timestamp,
)
from generator.tagupdater.tags import (
    FOLDER_ID_APPROVED,
    FOLDER_ID_READY_TO_PLAY,
)

FOLDER_TAG = {
    FOLDER_ID_APPROVED: "approved_date",
    FOLDER_ID_READY_TO_PLAY: "ready_to_play_date",
}

__all__ = [
    "FOLDER_ID_APPROVED",
    "FOLDER_ID_READY_TO_PLAY",
    "FOLDER_TAG",
    "SCOPES",
    "build_activity_service",
    "get_first_move_timestamp",
    "get_move_events",
    "normalise_timestamp",
]
