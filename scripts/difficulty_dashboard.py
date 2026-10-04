"""Streamlit dashboard for exploring `songbook-tools difficulty eval` runs.

Usage:
    uv run streamlit run scripts/difficulty_dashboard.py -- difficulty-eval/
"""

import sys
from dataclasses import fields
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from generator.difficulty import evaluation as ev

CAVEAT = (
    "Ground truth is the existing `difficulty` property, produced by the legacy "
    "rating model rather than human annotators: these numbers measure agreement "
    "with that scale."
)
METRIC_COLUMNS = {
    "n": "n",
    "failures": "failures",
    "mae": "MAE",
    "baseline_mae": "baseline MAE",
    "rmse": "RMSE",
    "bias": "bias",
    "pearson": "Pearson",
    "spearman": "Spearman",
    "within_0_5": "≤0.5",
    "within_1": "≤1.0",
    "level_accuracy": "level acc.",
}

LEGEND = alt.Legend(orient="bottom", direction="vertical", labelLimit=500)


def default_runs_dir() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "difficulty-eval"


def load_runs(paths):
    """Returns {run name: (header, rows)} for the given run files."""
    return {path.stem: ev.read_run(path) for path in paths}


def rows_frame(runs) -> pd.DataFrame:
    records = []
    for run, (_, rows) in runs.items():
        for r in rows:
            records.append({"run": run, **vars(r)})
    columns = ["run", *(f.name for f in fields(ev.ResultRow))]
    df = pd.DataFrame(records, columns=columns)
    df["err"] = df["pred"] - df["truth"]
    df["abs_err"] = df["err"].abs()
    return df


st.set_page_config(page_title="Difficulty eval", layout="wide")
st.title("LLM difficulty eval")
st.caption(CAVEAT)

runs_dir = Path(st.sidebar.text_input("Runs directory", default_runs_dir()))
run_files = sorted(
    runs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
)
if not run_files:
    st.info(f"No run files in `{runs_dir}`. Run `songbook-tools difficulty eval`.")
    st.stop()

by_name = {p.stem: p for p in run_files}
selected = st.sidebar.multiselect("Runs", list(by_name), default=[run_files[0].stem])
if not selected:
    st.stop()
runs = load_runs([by_name[name] for name in selected])
df = rows_frame(runs)
rated = df[df["pred"].notna() & df["error"].isna()]

st.header("Metrics")
metric_records = []
for run, (header, rows) in runs.items():
    metrics = ev.compute_metrics(rows)
    metric_records.append(
        {
            "run": run,
            "model": header.get("model"),
            "prompt": header.get("prompt_hash"),
            **{label: metrics.get(key) for key, label in METRIC_COLUMNS.items()},
        }
    )
st.dataframe(
    pd.DataFrame(metric_records).set_index("run"),
    column_config={
        label: st.column_config.NumberColumn(format="%.2f")
        for label in METRIC_COLUMNS.values()
        if label not in ("n", "failures")
    },
)
st.caption(
    "Baseline MAE: always predicting the mean truth of the sample. "
    "Level acc.: rounded prediction equals rounded truth."
)

if rated.empty:
    st.warning("No successful ratings in the selected runs.")
    st.stop()

left, right = st.columns(2)
with left:
    st.subheader("Truth vs prediction")
    axis_scale = alt.Scale(domain=[0.5, 5.5], nice=False)
    points = (
        alt.Chart(rated)
        .mark_circle(size=70, opacity=0.6)
        .encode(
            x=alt.X("truth:Q", scale=axis_scale, title="Ground truth"),
            y=alt.Y("pred:Q", scale=axis_scale, title="Prediction"),
            color=alt.Color("run:N", legend=LEGEND),
            tooltip=["name", "run", "truth", "pred"],
        )
    )
    diagonal = (
        alt.Chart(pd.DataFrame({"v": [0.5, 5.5]}))
        .mark_line(strokeDash=[4, 4], color="gray")
        .encode(
            x=alt.X("v:Q", scale=axis_scale, title="Ground truth"),
            y=alt.Y("v:Q", scale=axis_scale, title="Prediction"),
        )
    )
    st.altair_chart(diagonal + points, width="stretch")
with right:
    st.subheader("MAE per ground-truth level")
    level_records = [
        {"run": run, **lvl}
        for run, (_, rows) in runs.items()
        for lvl in ev.per_level_metrics(rows)
    ]
    st.altair_chart(
        alt.Chart(pd.DataFrame(level_records))
        .mark_bar()
        .encode(
            x="level:O",
            y="mae:Q",
            color=alt.Color("run:N", legend=LEGEND),
            xOffset="run:N",
            tooltip=["run", "level", "n", "mean_truth", "mean_pred", "mae"],
        ),
        width="stretch",
    )

focus = st.selectbox("Focus run (confusion matrix and misses)", selected)
_, focus_rows = runs[focus]

st.subheader("Confusion (rounded levels)")
matrix = ev.confusion(focus_rows)
cells = pd.DataFrame(
    [
        {"truth": t + 1, "pred": p + 1, "count": matrix[t][p]}
        for t in range(len(ev.LEVELS))
        for p in range(len(ev.LEVELS))
    ]
)
base = alt.Chart(cells).encode(x="pred:O", y=alt.Y("truth:O", sort="descending"))
st.altair_chart(
    base.mark_rect().encode(color=alt.Color("count:Q", scale=alt.Scale(scheme="blues")))
    + base.mark_text().encode(text="count:Q"),
    height=300,
)

failures = df[(df["run"] == focus) & df["error"].notna()]
if not failures.empty:
    with st.expander(f"{len(failures)} failed songs"):
        st.dataframe(failures[["name", "error"]], hide_index=True)

st.subheader("Misses")
misses = (
    rated[rated["run"] == focus]
    .sort_values("abs_err", ascending=False)
    .reset_index(drop=True)
)
event = st.dataframe(
    misses[["name", "level", "truth", "pred", "err"]],
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="misses",
)
picked = event.selection.rows[0] if event and event.selection.rows else 0
song = misses.iloc[picked]

st.subheader(song["name"])
st.write(f"Ground truth: **{song['truth']:.2f}** (level {song['level']})")
song_rows = df[df["id"] == song["id"]]
for column, (_, row) in zip(st.columns(len(song_rows)), song_rows.iterrows()):
    with column:
        st.markdown(f"**{row['run']}**")
        if pd.notna(row["error"]):
            st.error(row["error"])
        else:
            st.metric(
                "Prediction",
                f"{row['pred']:.1f}",
                f"{row['err']:+.2f}",
                delta_color="off",
            )
            st.write(row["reasoning"])
with st.expander("Prompt sent to the model"):
    st.text(song["input_text"] or "")
