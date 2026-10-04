"""Smoke tests for the Streamlit difficulty dashboard."""

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from generator.difficulty import evaluation as ev
from generator.difficulty.evaluation import ResultRow

DASHBOARD = str(Path(__file__).parent / "difficulty_dashboard.py")


def _write_run(path, preds):
    ev.write_header(path, {"model": "gemini-test", "prompt_hash": "abcd1234"})
    for i, (truth, pred) in enumerate(preds):
        ev.append_row(
            path,
            ResultRow(
                id=f"id-{i}",
                name=f"Song {i}",
                level=ev.level(truth),
                truth=truth,
                pred=pred,
                reasoning=f"reason {i}",
                input_text=f"sheet {i}",
                error=None if pred is not None else "ValueError: boom",
            ),
        )


def _app(monkeypatch, runs_dir):
    monkeypatch.setattr(sys, "argv", ["difficulty_dashboard.py", str(runs_dir)])
    return AppTest.from_file(DASHBOARD, default_timeout=20).run()


def test_dashboard_renders_runs(tmp_path, monkeypatch):
    _write_run(tmp_path / "a.jsonl", [(1.2, 1.5), (2.4, 3.0), (3.6, None), (4.8, 4.0)])
    _write_run(tmp_path / "b.jsonl", [(1.2, 2.0), (2.4, 2.5), (3.6, 3.5), (4.8, 3.0)])

    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    at.sidebar.multiselect[0].set_value(["a", "b"]).run()

    assert not at.exception
    assert len(at.dataframe) >= 3  # metrics, failures, misses
    assert any("Song 3" in h.value for h in at.subheader)  # biggest miss in "b"


@pytest.mark.parametrize("files", [[], ["empty.jsonl"]])
def test_dashboard_handles_missing_or_empty_runs(tmp_path, monkeypatch, files):
    for name in files:
        ev.write_header(tmp_path / name, {"model": "m"})

    at = _app(monkeypatch, tmp_path)

    assert not at.exception
    assert at.info or at.warning
