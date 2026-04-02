#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pyyaml>=6.0.2",
# ]
# ///
"""Read publish metadata from an edition YAML config and print it as JSON.

Usage: get-edition-publish-vars.py <edition-yaml-path>

Outputs a JSON object with 'visibility' (str) and 'pinned' (bool) fields.
Falls back to sensible defaults when the file is missing or unparseable.
"""

import json
import sys

import yaml


def main() -> None:
    visibility = "public"
    pinned = False

    if len(sys.argv) > 1:
        try:
            with open(sys.argv[1]) as f:
                cfg = yaml.safe_load(f)
            pub = cfg.get("publish", {}) if isinstance(cfg, dict) else {}
            visibility = pub.get("visibility", "public")
            pinned = bool(pub.get("pinned", False))
        except (OSError, yaml.YAMLError):
            pass

    print(json.dumps({"visibility": visibility, "pinned": pinned}))


if __name__ == "__main__":
    main()
