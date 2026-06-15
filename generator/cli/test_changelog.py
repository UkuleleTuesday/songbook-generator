import json

import fitz
import pytest
from click.testing import CliRunner

from ..cli import cli
from ..worker import toc as tocmod
from ..worker.models import File


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


def _write_songbook_pdf(path, names, cover_preface=2):
    """Render a real TOC and assemble a songbook-like PDF on disk.

    Files carry a 'difficulty' so the TOC renders difficulty glyphs, matching
    real songbooks (and making long/truncated entries detectable)."""
    files = [
        File(id=str(i), name=n, properties={"difficulty": str((i % 5) + 1)})
        for i, n in enumerate(names)
    ]
    tp, _ = tocmod.build_table_of_contents(files, 0)
    offset = cover_preface + len(tp)
    tp.close()
    tp, _ = tocmod.build_table_of_contents(files, offset)
    doc = fitz.open()
    for _ in range(cover_preface):
        doc.new_page()
    doc.insert_pdf(tp)
    for _ in files:
        doc.new_page()
    doc.save(str(path))
    doc.close()


def test_backfill_changelog_from_pdfs_builds_full_history(runner, tmp_path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    # Two historical (pre-manifest) publishes with a real song change between them.
    _write_songbook_pdf(
        pdfs / "ukulele-tuesday-songbook-current-2025-09-27.pdf",
        ["Angels - Robbie Williams", "Jolene - Dolly Parton"],
    )
    _write_songbook_pdf(
        pdfs / "ukulele-tuesday-songbook-current-2025-10-04.pdf",
        ["Angels - Robbie Williams", "Hey Jude - The Beatles"],
    )
    # A stray different-edition PDF that must be ignored.
    _write_songbook_pdf(
        pdfs / "ukulele-tuesday-songbook-complete-2025-10-04.pdf",
        ["Some Other Song - Nobody"],
    )
    out = tmp_path / "changes.json"

    result = runner.invoke(
        cli,
        [
            "backfill-changelog-from-pdfs",
            "--pdfs-dir",
            str(pdfs),
            "--edition",
            "current",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    history = json.loads(out.read_text())
    assert history["edition"] == "current"
    assert len(history["entries"]) == 1
    entry = history["entries"][0]
    assert entry["date"] == "2025-10-04"
    assert entry["source"] == "toc-page"
    assert entry["added"] == ["Hey Jude - The Beatles"]
    assert entry["removed"] == ["Jolene - Dolly Parton"]


def test_backfill_from_pdfs_resolves_truncated_toc_title_via_manifest(runner, tmp_path):
    # A long title is truncated in the historical TOC, but resolves to the full
    # manifest name -> it must NOT show up as added/removed.
    long_name = (
        "This Is An Extremely Long Song Title That Exceeds The Limit - The Verbose Band"
    )
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    _write_songbook_pdf(
        pdfs / "ukulele-tuesday-songbook-current-2025-09-27.pdf",
        [long_name, "Short Song - Artist"],
    )
    _write_manifest(
        manifests / "ukulele-tuesday-songbook-current-2026-02-06.manifest.json",
        [long_name, "Short Song - Artist", "New Song - X"],
        generated_at="2026-02-06T00:00:00+00:00",
        edition_id="current",
    )
    out = tmp_path / "changes.json"

    result = runner.invoke(
        cli,
        [
            "backfill-changelog-from-pdfs",
            "--pdfs-dir",
            str(pdfs),
            "--manifests-dir",
            str(manifests),
            "--edition",
            "current",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    history = json.loads(out.read_text())
    # Only the genuinely new song changed; the truncated long title resolved.
    assert len(history["entries"]) == 1
    entry = history["entries"][0]
    assert entry["added"] == ["New Song - X"]
    assert entry["removed"] == []
