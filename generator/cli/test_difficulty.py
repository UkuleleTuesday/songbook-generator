import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from ..difficulty import evaluation
from ..difficulty.rater import DifficultyRating
from ..tagupdater.tags import Context, SongSheetGoogleDocument
from ..worker.models import File
from .difficulty import difficulty

DOC_JSON = json.loads(
    (
        Path(__file__).parent.parent / "tagupdater" / "test_data" / "love_me_do.json"
    ).read_text()
)


@pytest.fixture
def holdout_files():
    """Three rated hold-out songs plus songs that must be ignored."""
    ids = [f"file-{i}" for i in range(200)]
    held = [i for i in ids if evaluation.is_holdout(i)][:3]
    not_held = next(i for i in ids if not evaluation.is_holdout(i))
    unrated = [i for i in ids if evaluation.is_holdout(i)][3]
    files = [
        File(id=fid, name=f"Song {fid}", properties={"difficulty": str(n + 1.5)})
        for n, fid in enumerate(held)
    ]
    files.append(File(id=not_held, name="Train", properties={"difficulty": "2"}))
    files.append(File(id=unrated, name="Unrated", properties={}))
    return files


@pytest.fixture
def cli_mocks(mocker, holdout_files):
    mocker.patch(
        "generator.cli.difficulty._init_services",
        return_value=(Mock(), Mock(), Mock(), Mock()),
    )
    source = mocker.patch("generator.cli.difficulty._make_song_source")
    source.return_value.collect_files.return_value = holdout_files
    mocker.patch(
        "generator.cli.difficulty._fetch_context",
        side_effect=lambda _docs, fid, name, client: Context(
            file=None,
            file_name=name,
            document=SongSheetGoogleDocument(json=DOC_JSON),
            genai_client=client,
        ),
    )
    return mocker.patch("generator.cli.difficulty.rate_difficulty")


def _run(tmp_path, *args):
    return CliRunner().invoke(
        difficulty,
        ["eval", "--output-dir", str(tmp_path), "--run-name", "r1", *args],
    )


def test_eval_records_results_and_resumes_only_failed_songs(
    tmp_path, cli_mocks, holdout_files
):
    cli_mocks.side_effect = [
        DifficultyRating(reasoning="easy", score=2.0),
        ValueError("bad answer"),
        DifficultyRating(reasoning="hard", score=4.0),
    ]

    result = _run(tmp_path, "--sample-size", "all")

    assert result.exit_code == 0, result.output
    header, rows = evaluation.read_run(tmp_path / "r1.jsonl")
    assert header["sample_size"] == 3
    assert sorted(r.name for r in rows) == sorted(f.name for f in holdout_files[:3])
    failed = [r for r in rows if r.error]
    assert len(failed) == 1 and "bad answer" in failed[0].error
    assert all("Love, love me do" in r.input_text for r in rows)
    assert "1 failures" in result.output

    cli_mocks.side_effect = [DifficultyRating(reasoning="ok", score=3.0)]
    result = _run(tmp_path, "--sample-size", "all")

    assert result.exit_code == 0, result.output
    assert cli_mocks.call_count == 4
    _, rows = evaluation.read_run(tmp_path / "r1.jsonl")
    assert not any(r.error for r in rows)
    assert "0 failures" in result.output


def test_eval_refuses_to_mix_models_in_one_run(tmp_path, cli_mocks):
    cli_mocks.return_value = DifficultyRating(reasoning="ok", score=3.0)
    assert _run(tmp_path).exit_code == 0

    result = _run(tmp_path, "--model", "other-model")

    assert result.exit_code != 0
    assert "different model or prompt" in result.output


def test_eval_rejects_invalid_sample_size(tmp_path, cli_mocks):
    result = _run(tmp_path, "--sample-size", "0")

    assert result.exit_code == 2
    assert "positive integer" in result.output
