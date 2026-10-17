from datetime import datetime, timezone
from pathlib import Path

import click
from google import genai
from googleapiclient.discovery import build

from ..common.caching import init_cache
from ..common.config import get_settings
from ..common.gdrive import GoogleDriveClient
from ..difficulty import evaluation
from ..difficulty.evaluation import ResultRow, Song
from ..difficulty.rater import (
    DEFAULT_MODEL,
    build_user_prompt,
    prompt_hash,
    rate_difficulty,
)
from ..tagupdater.tags import Context, SongSheetGoogleDocument
from ..worker.gcp import get_credentials
from ..worker.pdf import _make_song_source
from .utils import SubcmdGroup, _resolve_file_id


@click.group(cls=SubcmdGroup)
def difficulty():
    """Experimental LLM difficulty rating and its evaluation."""


def _init_services():
    """Drive, Docs, cache and Vertex clients, set up like ``tags update``."""
    settings = get_settings()
    credential_config = settings.google_cloud.credentials.get("tag-updater")
    if not credential_config:
        click.echo("Error: credential config 'tag-updater' not found.", err=True)
        raise click.Abort()
    creds = get_credentials(
        scopes=credential_config.scopes, target_principal=credential_config.principal
    )
    drive = build("drive", "v3", credentials=creds)
    docs = build("docs", "v1", credentials=creds)
    genai_client = genai.Client(
        vertexai=True,
        project=settings.google_cloud.project_id,
        location=settings.caching.gcs.region or "us-central1",
    )
    return drive, docs, init_cache(), genai_client


def _fetch_context(docs, file_id: str, file_name: str, genai_client) -> Context:
    doc_json = docs.documents().get(documentId=file_id).execute()
    return Context(
        file=None,
        file_name=file_name,
        document=SongSheetGoogleDocument(json=doc_json),
        genai_client=genai_client,
    )


def _parse_sample_size(_ctx, _param, value):
    if value is None or value == "all":
        return None
    try:
        size = int(value)
    except ValueError:
        raise click.BadParameter("must be a positive integer or 'all'")
    if size <= 0:
        raise click.BadParameter("must be a positive integer or 'all'")
    return size


@difficulty.command(name="rate")
@click.argument("file_identifier")
@click.option("--model", default=DEFAULT_MODEL, show_default=True)
@click.option("--verbose", "-v", is_flag=True, help="Also print the prompt sent.")
def rate(file_identifier, model, verbose):
    """Rate a single song sheet, for iterating on the prompt."""
    drive, docs, cache, genai_client = _init_services()
    gdrive_client = GoogleDriveClient(cache=cache, drive=drive)
    file_id = _resolve_file_id(gdrive_client, file_identifier)
    ctx = _fetch_context(docs, file_id, file_identifier, genai_client)
    if verbose:
        click.echo(build_user_prompt(ctx))
        click.echo("-" * 40)
    rating = rate_difficulty(ctx, model=model)
    click.echo(f"Score: {rating.score}")
    click.echo(f"Reasoning: {rating.reasoning}")


@difficulty.command(name="eval")
@click.option("--model", default=DEFAULT_MODEL, show_default=True)
@click.option(
    "--sample-size",
    default="30",
    show_default=True,
    callback=_parse_sample_size,
    help="Songs to rate from the hold-out set, or 'all'.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("difficulty-eval"),
    show_default=True,
)
@click.option(
    "--run-name",
    default=None,
    help="Defaults to <model>-<prompt hash>-<date>. Reuse a name to resume.",
)
def eval_cmd(model, sample_size, output_dir, run_name):
    """Rate a stratified hold-out sample and record results for the dashboard."""
    settings = get_settings()
    drive, docs, cache, genai_client = _init_services()

    click.echo("Fetching song sheets and their current difficulty...")
    files = _make_song_source(drive, cache).collect_files(
        settings.song_sheets.folder_ids
    )
    songs = []
    for f in files:
        truth = evaluation.parse_difficulty(f.properties.get("difficulty"))
        if truth is not None and evaluation.is_holdout(f.id):
            songs.append(Song(id=f.id, name=f.name, truth=truth))
    sample = evaluation.select_sample(songs, sample_size)
    click.echo(
        f"{len(files)} songs, {len(songs)} rated in hold-out, sampling {len(sample)}."
    )

    run_name = run_name or (
        f"{model}-{prompt_hash()}-{datetime.now(timezone.utc):%Y%m%d}"
    )
    path = output_dir / f"{run_name}.jsonl"
    done = set()
    if path.exists():
        header, rows = evaluation.read_run(path)
        if header.get("model") != model or header.get("prompt_hash") != prompt_hash():
            click.echo(
                f"Error: {path} was produced by a different model or prompt; "
                "pick another --run-name.",
                err=True,
            )
            raise click.Abort()
        done = {r.id for r in rows if r.error is None}
        click.echo(f"Resuming {path}: {len(done)} songs already rated.")
    else:
        evaluation.write_header(
            path,
            {
                "run_name": run_name,
                "model": model,
                "prompt_hash": prompt_hash(),
                "sample_size": len(sample),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    for i, song in enumerate(sample, start=1):
        if song.id in done:
            continue
        row = ResultRow(
            id=song.id,
            name=song.name,
            level=evaluation.level(song.truth),
            truth=song.truth,
        )
        try:
            ctx = _fetch_context(docs, song.id, song.name, genai_client)
            row.input_text = build_user_prompt(ctx)
            rating = rate_difficulty(ctx, model=model)
            row.pred, row.reasoning = rating.score, rating.reasoning
            click.echo(f"[{i}/{len(sample)}] {song.name}: {song.truth} -> {row.pred}")
        except Exception as e:  # noqa: BLE001 - recorded in the run file
            row.error = f"{type(e).__name__}: {e}"
            click.echo(f"[{i}/{len(sample)}] {song.name}: ERROR {row.error}", err=True)
        evaluation.append_row(path, row)

    _, rows = evaluation.read_run(path)
    m = evaluation.compute_metrics(rows)
    if m["n"]:
        spearman = "n/a" if m["spearman"] is None else f"{m['spearman']:.2f}"
        click.echo(
            f"MAE {m['mae']:.2f} (baseline {m['baseline_mae']:.2f}), "
            f"Spearman {spearman}, {m['failures']} failures. Results: {path}"
        )
    else:
        click.echo(f"No successful ratings; {m['failures']} failures. See {path}")
