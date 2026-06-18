# Spike / Design Note — Unify Drive change detection (event-driven cache + tagging)

**Relates to:** [#151](https://github.com/UkuleleTuesday/songbook-generator/issues/151)
(event-driven epic), [#186](https://github.com/UkuleleTuesday/songbook-generator/issues/186) /
[#279](https://github.com/UkuleleTuesday/songbook-generator/pull/279) (Drive
push-notifications), [#206](https://github.com/UkuleleTuesday/songbook-generator/issues/206)
(cache-updater on file-changes), [#390](https://github.com/UkuleleTuesday/songbook-generator/issues/390)
/ [#391](https://github.com/UkuleleTuesday/songbook-generator/issues/391) (drivewatcher
cadence), and the cost-savings spike (`cost-savings-2026-03-01-to-2026-06-30.md`).

## Problem statement

The move to an event-driven architecture (#151) was started but left
half-finished, producing an awkward state: change detection is **duplicated and
uncoordinated**, the cadence is mismatched with downstream consumers, and an
end-state (webhook push) was prototyped then abandoned. This note records the
current state, the target shape, and an **incremental, low-risk migration path**
so the area can be finished deliberately rather than rewritten big-bang.

It also fixes the framing on one recurring question — *"should we use Drive
`changes.watch` webhooks?"* — by separating **how the detector is triggered**
(poll vs push) from **what the detector feeds** (the real work).

## Current state (verified in code)

Two **independent** Drive change-detection loops exist:

```
per-minute scheduler ─▶ drivewatcher ─▶ drive-file-changes topic ─▶ tagupdater (ONLY consumer)

15-min scheduler ─────▶ cache-updater ─▶ own Drive diff ─▶ sync PDFs to GCS cache + merge
```

- **drivewatcher** (`generator/drivewatcher/main.py`): triggered by its own
  `DRIVEWATCHER_TRIGGER_PUBSUB_TOPIC` on a `* * * * *` cron (`deploy.yaml`).
  Each run reads a checkpoint blob `drivewatcher/metadata.json` from the worker
  cache bucket (`_get_last_check_time` → `get_blob`) and, **unconditionally**,
  rewrites it (`_save_check_time` → `upload_from_string`) — even on no-change
  runs. On changes it publishes `changed_files` (each with `id`, `name`,
  `folder_id`) to `DRIVE_CHANGES_PUBSUB_TOPIC`.
- **tagupdater** is the **only** subscriber to `drive-file-changes`
  (`deploy.yaml` `trigger_topic: DRIVE_CHANGES_PUBSUB_TOPIC`).
- **cache-updater** (`generator/cache_updater/main.py`): triggered by a
  **separate** `CACHE_REFRESH_PUBSUB_TOPIC`, published by the
  `trigger-cache-updater-job` scheduler every 15 min (`deploy-gcs.sh`). It runs
  its **own** Drive diff — `sync_cache(..., modified_after=last_merge_time)` →
  `query_drive_files(modified_after=…)` — independent of the drivewatcher.

### Why it's awkward
1. **Two pollers querying Drive for the same changes** — one per minute (tags),
   one per 15 min (cache) — with no shared cursor.
2. **Cadence mismatch / over-precision.** The drivewatcher polls every 60 s, but
   everything downstream is far coarser: cache refresh ≤15 min, songbook
   generation hourly. The minute-by-minute precision buys nothing today.
3. **Intent/reality drift.** The drivewatcher docstring says "every 5 minutes";
   the cron is every minute.
4. **Abandoned end-state.** The webhook push pipeline (#186) was prototyped in
   #279 (adds `drivewebhook/` + `drivewatcher/watch.py`, cron → `0 */23 * * *`)
   and left in draft since March.
5. **Cost.** Per Level-1 billing analysis, Cloud Storage cost is **operations-
   dominated** (~80%), and the unconditional per-minute checkpoint write plus the
   cache-updater's blind 15-min `list_blobs`/full-folder diff are direct
   contributors.

## Target state

One change detector, fanning the **same** change events out to all consumers,
each doing **targeted** work:

```
            ┌─ tagupdater       (update tags for changed files)
change source ─▶ changed_files {id,name,folder} ─┼─ cache rebuild   (sync ONLY changed file IDs)
 (drivewatcher)                                  └─ (later) regenerate affected editions
```

The drivewatcher already emits `changed_files` with IDs, so consumers can act on
exactly what changed instead of re-scanning everything.

## Design principles

1. **Decouple the trigger from the fan-out.** "Poll vs webhook" only decides how
   the detector *wakes up*; it is independent of the unify/fan-out/targeted-rebuild
   design. Build the consumer side on a poll now; a `changes.watch` trigger
   (#186/#279) can be swapped in later **without touching any consumer logic**.
   The webhook is therefore an optional *last* step, never a prerequisite.
2. **Event-driven + periodic reconcile.** Pure event-driven systems drift when a
   notification is missed; polling is self-healing. Steady state should be
   *event-driven targeted rebuilds* **plus** a *daily full reconcile sync* as a
   backstop. The backstop is what makes it safe to drop the minute-by-minute
   cadence.
3. **Carry the payload.** Consumers act on the `changed_files` list, not by
   re-querying Drive, so detection happens once.

## Migration path (incremental)

1. **Now — cost/hygiene (safe, no architecture change):** #390 — slow the
   drivewatcher cron (`* * * * *` → `*/10 * * * *`), fix the stale docstring, and
   stop rewriting `metadata.json` on no-change runs. #391 — stop creating a
   per-PR drivewatcher scheduler. Only affects tag latency today.
2. **Consolidation — the real fix (#206):** make the drivewatcher the single
   detector; have the cache-updater consume `drive-file-changes` and sync only the
   changed file IDs; add a daily full reconcile sync as the backstop; retire the
   separate 15-min cache poll. This deletes the duplicate poller and finishes the
   half-migration.
3. **Optional, later (#186/#279):** swap the poll trigger for a `changes.watch`
   webhook **iff** a genuine sub-minute latency requirement appears. Consumer
   logic is unchanged.

## Decision on the webhook (#186/#279)

**Defer.** It is a latency/scale solution; the system has no requirement tighter
than minutes (cache ≤15 min, generation hourly). Its operational cost is real (a
public HTTPS endpoint plus a channel-renewal job whose failure mode — 0 or 2 live
channels — is silent). Keep #186 as the tracked design and #279 as a dormant POC;
revisit only if real-time tagging/generation becomes a product goal.

## Related state-storage note

The drivewatcher checkpoint lives as a GCS blob while a parallel Firestore
metadata migration runs (#398). If/when this area is touched, the checkpoint (a
tiny mutable cursor) is a natural fit for Firestore (free-tier) rather than an
object rewrite — but that's cleanup, not a blocker, and it's subsumed by step 1
(stop writing it every run) regardless.
