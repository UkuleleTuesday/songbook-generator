from collections import Counter

import pytest

from . import evaluation as ev
from .evaluation import ResultRow, Song


@pytest.mark.parametrize(
    "value, expected",
    [("3.009", 3.009), ("1", 1.0), ("", None), (None, None), ("abc", None)],
)
def test_parse_difficulty(value, expected):
    assert ev.parse_difficulty(value) == expected


@pytest.mark.parametrize(
    "value, expected", [(0.81, 1), (1.49, 1), (1.5, 2), (2.5, 3), (5.03, 5)]
)
def test_level_rounds_half_up_and_clamps(value, expected):
    assert ev.level(value) == expected


def test_is_holdout_is_deterministic_and_reserves_about_a_fifth():
    ids = [f"file-{i}" for i in range(5000)]
    held = [i for i in ids if ev.is_holdout(i)]

    assert held == [i for i in ids if ev.is_holdout(i)]
    assert 0.18 < len(held) / len(ids) < 0.22


def _songs(counts):
    """Synthetic songs: ``counts`` maps level -> number of songs."""
    return [
        Song(id=f"{lvl}-{i}", name=f"Song {lvl}-{i}", truth=float(lvl))
        for lvl, n in counts.items()
        for i in range(n)
    ]


def test_select_sample_keeps_rare_levels_and_is_roughly_proportional():
    songs = _songs({1: 3, 2: 40, 3: 35, 4: 10, 5: 2})

    sample = ev.select_sample(songs, 30)
    counts = Counter(ev.level(s.truth) for s in sample)

    assert len(sample) == 30
    assert counts[1] == 2 and counts[5] == 2
    assert counts[2] > counts[3] > counts[4] >= 2


def test_select_sample_is_deterministic_regardless_of_input_order():
    songs = _songs({1: 5, 2: 20, 3: 20, 4: 5})

    assert ev.select_sample(songs, 12) == ev.select_sample(songs[::-1], 12)


def test_select_sample_returns_everything_when_size_is_none_or_too_large():
    songs = _songs({2: 3, 3: 2})

    assert len(ev.select_sample(songs, None)) == 5
    assert len(ev.select_sample(songs, 50)) == 5


def test_select_sample_smaller_than_level_minimums():
    sample = ev.select_sample(_songs({1: 5, 2: 5, 3: 5, 4: 5, 5: 5}), 3)

    assert len(sample) == 3


def test_run_file_round_trip_keeps_latest_row_per_song(tmp_path):
    path = tmp_path / "runs" / "run.jsonl"
    ev.write_header(path, {"model": "m"})
    ev.append_row(path, ResultRow("a", "A", 2, 2.0, error="boom"))
    ev.append_row(path, ResultRow("b", "B", 3, 3.0, pred=3.5, reasoning="ok"))
    ev.append_row(path, ResultRow("a", "A", 2, 2.0, pred=2.5, reasoning="ok"))

    header, rows = ev.read_run(path)

    assert header == {"model": "m"}
    assert {r.id: r.pred for r in rows} == {"a": 2.5, "b": 3.5}


def _rows(pairs):
    return [
        ResultRow(str(i), str(i), ev.level(t), t, pred=p)
        for i, (t, p) in enumerate(pairs)
    ]


def test_compute_metrics_on_known_values():
    rows = _rows([(1.0, 2.0), (2.0, 2.0), (3.0, 4.0), (4.0, 3.0)])
    rows.append(ResultRow("x", "x", 2, 2.0, error="boom"))

    m = ev.compute_metrics(rows)

    assert m["n"] == 4 and m["failures"] == 1
    assert m["mae"] == pytest.approx(0.75)
    assert m["rmse"] == pytest.approx(0.75**0.5)
    assert m["bias"] == pytest.approx(0.25)
    assert m["within_0_5"] == pytest.approx(0.25)
    assert m["within_1"] == pytest.approx(1.0)
    assert m["level_accuracy"] == pytest.approx(0.25)
    assert m["baseline_mae"] == pytest.approx(1.0)
    assert m["pearson"] == pytest.approx(2.5 / 13.75**0.5)


def test_spearman_handles_ties_and_perfect_order():
    assert ev.compute_metrics(_rows([(1, 1), (2, 3), (3, 4)]))["spearman"] == (
        pytest.approx(1.0)
    )
    tied = ev.compute_metrics(_rows([(1, 2), (2, 2), (3, 4), (4, 5)]))
    assert tied["spearman"] == pytest.approx(0.9486833)


def test_compute_metrics_with_no_successful_rows():
    rows = [ResultRow("x", "x", 2, 2.0, error="boom")]

    assert ev.compute_metrics(rows) == {"n": 0, "failures": 1}


def test_constant_predictions_have_no_correlation():
    assert ev.compute_metrics(_rows([(1, 3), (2, 3), (4, 3)]))["pearson"] is None


def test_per_level_metrics_and_confusion():
    rows = _rows([(1.0, 1.5), (1.2, 3.0), (3.0, 3.0)])

    assert ev.per_level_metrics(rows) == [
        {"level": 1, "n": 2, "mean_truth": 1.1, "mean_pred": 2.25, "mae": 1.15},
        {"level": 3, "n": 1, "mean_truth": 3.0, "mean_pred": 3.0, "mae": 0.0},
    ]
    matrix = ev.confusion(rows)
    assert matrix[0][1] == 1  # truth 1, pred 1.5 -> level 2
    assert matrix[0][2] == 1
    assert matrix[2][2] == 1
    assert sum(map(sum, matrix)) == 3
