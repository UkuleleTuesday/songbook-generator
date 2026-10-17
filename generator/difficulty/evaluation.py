"""Hold-out sampling, run files and metrics for the difficulty rater."""

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

HOLDOUT_PERCENT = 20
MIN_PER_LEVEL = 2
LEVELS = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class Song:
    """A song with an existing (ground truth) difficulty rating."""

    id: str
    name: str
    truth: float


@dataclass
class ResultRow:
    """One rated song in a run file."""

    id: str
    name: str
    level: int
    truth: float
    pred: Optional[float] = None
    reasoning: Optional[str] = None
    input_text: Optional[str] = None
    error: Optional[str] = None


def parse_difficulty(value: Optional[str]) -> Optional[float]:
    """Parses a stored difficulty property, returning None when unusable."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def level(difficulty: float) -> int:
    """Rounds a difficulty (half up) to its 1-5 rubric level."""
    return int(min(max(math.floor(difficulty + 0.5), LEVELS[0]), LEVELS[-1]))


def _hash(file_id: str) -> str:
    return hashlib.sha256(file_id.encode()).hexdigest()


def is_holdout(file_id: str, percent: int = HOLDOUT_PERCENT) -> bool:
    """Deterministically reserves ``percent`` of songs for evaluation only."""
    return int(_hash(file_id), 16) % 100 < percent


def select_sample(songs: Iterable[Song], size: Optional[int]) -> List[Song]:
    """
    Picks a sample stratified by rubric level.

    Each level gets at least ``MIN_PER_LEVEL`` songs when available so rare
    levels stay represented; the rest is split proportionally. Songs within a
    level are taken in hash order, so the same input gives the same sample.
    ``size=None`` returns every song.
    """
    by_level: Dict[int, List[Song]] = defaultdict(list)
    for song in songs:
        by_level[level(song.truth)].append(song)
    for members in by_level.values():
        members.sort(key=lambda s: _hash(s.id))

    total = sum(len(m) for m in by_level.values())
    if size is None or size >= total:
        return [s for lvl in sorted(by_level) for s in by_level[lvl]]

    minimum = min(MIN_PER_LEVEL, size // max(len(by_level), 1))
    quota = {lvl: min(minimum, len(m)) for lvl, m in by_level.items()}
    remaining = size - sum(quota.values())
    while remaining > 0:
        open_levels = [lvl for lvl in by_level if quota[lvl] < len(by_level[lvl])]
        # Largest gap between proportional target and current quota goes first.
        target = {lvl: size * len(by_level[lvl]) / total for lvl in open_levels}
        lvl = max(open_levels, key=lambda lv: (target[lv] - quota[lv], -lv))
        quota[lvl] += 1
        remaining -= 1
    return [s for lvl in sorted(by_level) for s in by_level[lvl][: quota[lvl]]]


# --- Run files: a JSON header line followed by one ResultRow per line. ---


def write_header(path: Path, header: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"header": header}) + "\n")


def append_row(path: Path, row: ResultRow) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def read_run(path: Path) -> Tuple[dict, List[ResultRow]]:
    """Reads a run file; later rows for the same song replace earlier ones."""
    header: dict = {}
    rows: Dict[str, ResultRow] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if "header" in record:
                header = record["header"]
            else:
                rows[record["id"]] = ResultRow(**record)
    return header, list(rows.values())


# --- Metrics ---


def _rank(values: np.ndarray) -> np.ndarray:
    """Average ranks (ties share the mean rank), as used by Spearman."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(len(values))
    for value in np.unique(values):
        tied = values == value
        ranks[tied] = ranks[tied].mean()
    return ranks


def _pearson(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    if len(a) < 2 or a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def compute_metrics(rows: List[ResultRow]) -> dict:
    """Agreement metrics over successfully rated rows, plus a mean baseline."""
    rated = [r for r in rows if r.pred is not None and r.error is None]
    metrics = {"n": len(rated), "failures": len(rows) - len(rated)}
    if not rated:
        return metrics
    truth = np.array([r.truth for r in rated])
    pred = np.array([r.pred for r in rated])
    err = pred - truth
    metrics.update(
        mae=float(np.abs(err).mean()),
        rmse=float(np.sqrt((err**2).mean())),
        bias=float(err.mean()),
        pearson=_pearson(truth, pred),
        spearman=_pearson(_rank(truth), _rank(pred)),
        within_0_5=float((np.abs(err) <= 0.5).mean()),
        within_1=float((np.abs(err) <= 1.0).mean()),
        level_accuracy=float(
            np.mean([level(t) == level(p) for t, p in zip(truth, pred)])
        ),
        baseline_mae=float(np.abs(truth - truth.mean()).mean()),
    )
    return metrics


def per_level_metrics(rows: List[ResultRow]) -> List[dict]:
    """Mean truth, mean prediction and MAE for each ground-truth level."""
    rated = [r for r in rows if r.pred is not None and r.error is None]
    result = []
    for lvl in LEVELS:
        members = [r for r in rated if r.level == lvl]
        if not members:
            continue
        truth = np.array([r.truth for r in members])
        pred = np.array([r.pred for r in members])
        result.append(
            {
                "level": lvl,
                "n": len(members),
                "mean_truth": float(truth.mean()),
                "mean_pred": float(pred.mean()),
                "mae": float(np.abs(pred - truth).mean()),
            }
        )
    return result


def confusion(rows: List[ResultRow]) -> List[List[int]]:
    """5x5 counts: ``matrix[truth_level - 1][pred_level - 1]``."""
    matrix = [[0] * len(LEVELS) for _ in LEVELS]
    for r in rows:
        if r.pred is not None and r.error is None:
            matrix[level(r.truth) - 1][level(r.pred) - 1] += 1
    return matrix
