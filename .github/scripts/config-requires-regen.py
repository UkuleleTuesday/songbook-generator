#!/usr/bin/env python3
"""Decide whether an edition config change requires regenerating the songbook.

Usage:
    config-requires-regen.py <old-config.yaml> <new-config.yaml>

Exits 0 when the configs differ outside the `publish` block (regeneration
needed), 1 when only publish metadata changed — that is handled by the
sync-publish-metadata workflow without touching the published book — or when
the new config is `frozen`.
"""

import sys

import yaml


def load_without_publish(path):
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    if isinstance(cfg, dict):
        cfg.pop("publish", None)
    return cfg


def main() -> None:
    old, new = sys.argv[1], sys.argv[2]
    new_cfg = load_without_publish(new)
    if isinstance(new_cfg, dict) and new_cfg.get("frozen"):
        print(f"{new}: edition is frozen, not regenerating")
        sys.exit(1)
    sys.exit(0 if load_without_publish(old) != new_cfg else 1)


if __name__ == "__main__":
    main()
