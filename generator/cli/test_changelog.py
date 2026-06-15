import json

import pytest
from click.testing import CliRunner

from ..cli import cli


@pytest.fixture
def runner():
    return CliRunner()


def _write_manifest(path, file_names, generated_at=None, edition_id=None):
    data = {"content_info": {"file_names": list(file_names)}}
    if generated_at is not None:
        data["generated_at"] = generated_at
    if edition_id is not None:
        data["edition"] = {"id": edition_id}
    path.write_text(json.dumps(data))


def test_update_changelog_appends_entry(runner, tmp_path):
    new = tmp_path / "new.manifest.json"
    old = tmp_path / "old.manifest.json"
    out = tmp_path / "changes.json"
    _write_manifest(new, ["A", "B", "C"], generated_at="2026-06-09T00:00:00+00:00")
    _write_manifest(old, ["A", "C", "D"], generated_at="2026-06-02T00:00:00+00:00")

    result = runner.invoke(
        cli,
        [
            "update-changelog",
            "--new-manifest",
            str(new),
            "--previous-manifest",
            str(old),
            "--previous-manifest-filename",
            "published-old.manifest.json",
            "--edition",
            "current",
            "--manifest-filename",
            "published-new.manifest.json",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    history = json.loads(out.read_text())
    assert history["edition"] == "current"
    assert len(history["entries"]) == 1
    entry = history["entries"][0]
    assert entry["manifest_filename"] == "published-new.manifest.json"
    assert entry["previous_manifest"] == "published-old.manifest.json"
    assert entry["added"] == ["B"]
    assert entry["removed"] == ["D"]


def test_update_changelog_noop_leaves_history_unchanged(runner, tmp_path):
    new = tmp_path / "new.manifest.json"
    old = tmp_path / "old.manifest.json"
    changes = tmp_path / "changes.json"
    _write_manifest(new, ["A", "B"], generated_at="2026-06-09T00:00:00+00:00")
    _write_manifest(old, ["B", "A"], generated_at="2026-06-09T00:00:00+00:00")
    existing = {
        "edition": "current",
        "entries": [
            {
                "manifest_filename": "earlier.manifest.json",
                "added": ["A"],
                "removed": [],
            }
        ],
    }
    changes.write_text(json.dumps(existing))

    result = runner.invoke(
        cli,
        [
            "update-changelog",
            "--new-manifest",
            str(new),
            "--previous-manifest",
            str(old),
            "--changes",
            str(changes),
            "--edition",
            "current",
            "--output",
            str(changes),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "history unchanged" in result.output
    history = json.loads(changes.read_text())
    assert history["entries"] == existing["entries"]


def test_update_changelog_first_publish_none(runner, tmp_path):
    new = tmp_path / "new.manifest.json"
    out = tmp_path / "changes.json"
    _write_manifest(new, ["A", "B"], generated_at="2026-06-09T00:00:00+00:00")

    result = runner.invoke(
        cli,
        [
            "update-changelog",
            "--new-manifest",
            str(new),
            "--previous-manifest",
            "none",
            "--edition",
            "current",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    history = json.loads(out.read_text())
    assert history == {"edition": "current", "entries": []}


def test_backfill_changelog_builds_history(runner, tmp_path):
    hist_dir = tmp_path / "hist"
    hist_dir.mkdir()
    _write_manifest(
        hist_dir / "c-2026-05-26.manifest.json",
        ["A"],
        "2026-05-26T00:00:00+00:00",
        "current",
    )
    _write_manifest(
        hist_dir / "c-2026-06-02.manifest.json",
        ["A", "B"],
        "2026-06-02T00:00:00+00:00",
        "current",
    )
    _write_manifest(
        hist_dir / "c-2026-06-09.manifest.json",
        ["A", "C"],
        "2026-06-09T00:00:00+00:00",
        "current",
    )
    # Stray manifest for another edition under the same prefix -> excluded.
    _write_manifest(
        hist_dir / "complete-2026-03-09.manifest.json",
        ["X"],
        "2026-03-09T00:00:00+00:00",
        "complete",
    )
    out = tmp_path / "changes.json"

    result = runner.invoke(
        cli,
        [
            "backfill-changelog",
            "--manifests-dir",
            str(hist_dir),
            "--edition",
            "current",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    history = json.loads(out.read_text())
    assert [e["manifest_filename"] for e in history["entries"]] == [
        "c-2026-06-09.manifest.json",
        "c-2026-06-02.manifest.json",
    ]
    assert history["entries"][0]["added"] == ["C"]
    assert history["entries"][0]["removed"] == ["B"]
