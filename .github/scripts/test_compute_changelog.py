import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).parent / "compute-changelog.py"
_spec = importlib.util.spec_from_file_location("compute_changelog", _SCRIPT)
ccl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccl)


def test_basic_add_and_remove():
    result = ccl.compute_changelog(
        new_names=["A", "B", "C"],
        old_names=["A", "C", "D"],
        previous_manifest="prev.manifest.json",
        previous_generated_at="2026-05-31T03:00:00+00:00",
    )
    assert result == {
        "previous_manifest": "prev.manifest.json",
        "previous_generated_at": "2026-05-31T03:00:00+00:00",
        "added": ["B"],
        "removed": ["D"],
        "added_count": 1,
        "removed_count": 1,
    }


def test_added_is_sorted():
    result = ccl.compute_changelog(
        new_names=["Z", "A"],
        old_names=[],
        previous_manifest="prev.manifest.json",
        previous_generated_at="2026-05-31T03:00:00+00:00",
    )
    assert result["added"] == ["A", "Z"]
    assert result["removed"] == []


def test_first_run_no_previous():
    result = ccl.compute_changelog(
        new_names=["A", "B"],
        old_names=None,
        previous_manifest=None,
        previous_generated_at=None,
    )
    assert result == {
        "previous_manifest": None,
        "previous_generated_at": None,
        "added": [],
        "removed": [],
        "added_count": 0,
        "removed_count": 0,
    }


def test_no_changes():
    result = ccl.compute_changelog(
        new_names=["A", "B"],
        old_names=["B", "A"],
        previous_manifest="prev.manifest.json",
        previous_generated_at="2026-05-31T03:00:00+00:00",
    )
    assert result["added"] == []
    assert result["removed"] == []
    assert result["added_count"] == 0
    assert result["removed_count"] == 0


def test_load_file_names_missing():
    assert ccl.load_file_names({}) == []
    assert ccl.load_file_names({"content_info": {}}) == []
    assert ccl.load_file_names({"content_info": {"file_names": None}}) == []
    assert ccl.load_file_names({"content_info": {"file_names": ["X"]}}) == ["X"]


def _write_manifest(path: Path, file_names, generated_at=None):
    data = {"content_info": {"file_names": file_names}}
    if generated_at is not None:
        data["generated_at"] = generated_at
    path.write_text(json.dumps(data))


def test_main_enriches_manifest_in_place(tmp_path, monkeypatch):
    new = tmp_path / "new.manifest.json"
    old = tmp_path / "old.manifest.json"
    _write_manifest(new, ["A", "B", "C"])
    _write_manifest(old, ["A", "C", "D"], generated_at="2026-05-31T03:00:00+00:00")

    monkeypatch.setattr(
        ccl.sys,
        "argv",
        ["compute-changelog.py", str(new), str(old), "old-name.manifest.json"],
    )
    ccl.main()

    result = json.loads(new.read_text())
    assert result["content_info"]["file_names"] == ["A", "B", "C"]
    assert result["changelog"] == {
        "previous_manifest": "old-name.manifest.json",
        "previous_generated_at": "2026-05-31T03:00:00+00:00",
        "added": ["B"],
        "removed": ["D"],
        "added_count": 1,
        "removed_count": 1,
    }


def test_main_first_run_none(tmp_path, monkeypatch):
    new = tmp_path / "new.manifest.json"
    _write_manifest(new, ["A", "B"])

    monkeypatch.setattr(ccl.sys, "argv", ["compute-changelog.py", str(new), "none"])
    ccl.main()

    result = json.loads(new.read_text())
    assert result["changelog"]["added"] == []
    assert result["changelog"]["removed"] == []
    assert result["changelog"]["previous_manifest"] is None


def test_main_missing_previous_degrades(tmp_path, monkeypatch):
    new = tmp_path / "new.manifest.json"
    _write_manifest(new, ["A", "B"])
    missing = tmp_path / "does-not-exist.json"

    monkeypatch.setattr(
        ccl.sys, "argv", ["compute-changelog.py", str(new), str(missing)]
    )
    ccl.main()

    result = json.loads(new.read_text())
    assert result["changelog"]["added"] == []
    assert result["changelog"]["previous_manifest"] is None
