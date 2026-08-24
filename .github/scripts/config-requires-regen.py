#!/usr/bin/env python3
"""Decide whether an edition config change requires regenerating the songbook.

Usage:
    config-requires-regen.py <old-config.yaml> <new-config.yaml>

Exits 0 when the configs differ outside the `publish` block (regeneration
needed), 1 when only publish metadata changed — that is handled by the
sync-publish-metadata workflow without touching the published book.
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
    sys.exit(0 if load_without_publish(old) != load_without_publish(new) else 1)


if __name__ == "__main__":
    main()
