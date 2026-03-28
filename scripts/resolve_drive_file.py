"""
Resolve a Google Drive file identifier (ID or name) and print a tagupdater
Pub/Sub message payload to stdout.

Usage:
    uv run python scripts/resolve_drive_file.py <file_id_or_name>

Reads GDRIVE_SONG_SHEETS_FOLDER_IDS from the environment to scope name searches.
Exits non-zero if the file cannot be resolved unambiguously.
"""

import datetime
import json
import os
import sys

from google.auth import default
from googleapiclient.discovery import build


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <file_id_or_name>", file=sys.stderr)
        sys.exit(1)

    identifier = sys.argv[1]
    folder_ids = [
        f.strip()
        for f in os.environ.get("GDRIVE_SONG_SHEETS_FOLDER_IDS", "").split(",")
        if f.strip()
    ]

    creds, _ = default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
    drive = build("drive", "v3", credentials=creds)

    # Looks like a Drive file ID: long, no spaces
    if len(identifier) > 20 and " " not in identifier:
        print(f"Fetching file by ID: {identifier}", file=sys.stderr)
        result = (
            drive.files()
            .get(fileId=identifier, fields="id,name,mimeType,parents,properties")
            .execute()
        )
        files = [result]
    else:
        if not folder_ids:
            print("Error: GDRIVE_SONG_SHEETS_FOLDER_IDS is not set.", file=sys.stderr)
            sys.exit(1)
        escaped = identifier.replace("'", "\\'")
        parent_clause = " or ".join(f"'{fid}' in parents" for fid in folder_ids)
        query = f"name contains '{escaped}' and ({parent_clause}) and trashed = false"
        print(f"Searching Drive: {query}", file=sys.stderr)
        resp = (
            drive.files()
            .list(
                q=query,
                pageSize=10,
                fields="files(id,name,mimeType,parents,properties)",
            )
            .execute()
        )
        files = resp.get("files", [])

    if not files:
        print(f"Error: No file found for '{identifier}'.", file=sys.stderr)
        sys.exit(1)

    if len(files) > 1:
        print(f"Error: Multiple files matched '{identifier}':", file=sys.stderr)
        for f in files:
            print(f"  - {f['name']} (ID: {f['id']})", file=sys.stderr)
        sys.exit(1)

    f = files[0]
    print(f"Resolved: {f['name']} (ID: {f['id']})", file=sys.stderr)

    message = {
        "check_time": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "file_count": 1,
        "folders_checked": f.get("parents", []),
        "changed_files": [
            {
                "id": f["id"],
                "name": f["name"],
                "mime_type": f.get("mimeType", ""),
                "parents": f.get("parents", []),
                "properties": f.get("properties", {}),
            }
        ],
    }
    print(json.dumps(message))


if __name__ == "__main__":
    main()
