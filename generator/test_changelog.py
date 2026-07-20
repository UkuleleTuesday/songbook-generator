from .changelog import (
    backfill_history,
    build_entry,
    build_timeline,
    build_vocabulary,
    canon,
    compose_entries,
    diff_keyed,
    diff_songs,
    empty_history,
    load_file_names,
    resolve,
    short_key,
    update_history,
)


def _manifest(file_names, generated_at=None, edition_id=None):
    m = {"content_info": {"file_names": list(file_names)}}
    if generated_at is not None:
        m["generated_at"] = generated_at
    if edition_id is not None:
        m["edition"] = {"id": edition_id}
    return m


def test_load_file_names_missing():
    assert load_file_names({}) == []
    assert load_file_names({"content_info": {}}) == []
    assert load_file_names({"content_info": {"file_names": None}}) == []
    assert load_file_names({"content_info": {"file_names": ["X"]}}) == ["X"]


def test_diff_songs_sorted():
    added, removed = diff_songs(["Z", "A", "B"], ["A", "C"])
    assert added == ["B", "Z"]
    assert removed == ["C"]


def test_build_entry_basic():
    entry = build_entry(
        new_manifest=_manifest(
            ["A", "B", "C"], generated_at="2026-06-09T00:00:00+00:00"
        ),
        previous_manifest=_manifest(
            ["A", "C", "D"], generated_at="2026-06-02T00:00:00+00:00"
        ),
        manifest_filename="new.manifest.json",
        previous_manifest_filename="old.manifest.json",
    )
    assert entry == {
        "generated_at": "2026-06-09T00:00:00+00:00",
        "manifest_filename": "new.manifest.json",
        "previous_manifest": "old.manifest.json",
        "previous_generated_at": "2026-06-02T00:00:00+00:00",
        "added": ["B"],
        "removed": ["D"],
        "added_count": 1,
        "removed_count": 1,
    }


def test_build_entry_none_on_first_publish():
    assert (
        build_entry(
            new_manifest=_manifest(["A", "B"]),
            previous_manifest=None,
            manifest_filename="new.manifest.json",
        )
        is None
    )


def test_build_entry_none_on_no_change():
    assert (
        build_entry(
            new_manifest=_manifest(["A", "B"]),
            previous_manifest=_manifest(["B", "A"]),
            manifest_filename="new.manifest.json",
            previous_manifest_filename="old.manifest.json",
        )
        is None
    )


def test_update_history_prepends_newest_first():
    history = empty_history("current")
    e1 = {"manifest_filename": "m1.json", "added": ["A"], "removed": []}
    e2 = {"manifest_filename": "m2.json", "added": ["B"], "removed": []}
    history = update_history(history, e1, "current")
    history = update_history(history, e2, "current")
    assert [e["manifest_filename"] for e in history["entries"]] == [
        "m2.json",
        "m1.json",
    ]
    assert history["edition"] == "current"


def test_update_history_none_entry_is_noop():
    history = {"edition": "current", "entries": [{"manifest_filename": "m1.json"}]}
    result = update_history(history, None, "current")
    assert result["entries"] == [{"manifest_filename": "m1.json"}]


def test_update_history_upsert_by_filename_is_idempotent():
    history = empty_history("current")
    entry = {"manifest_filename": "m.json", "added": ["A"], "removed": []}
    history = update_history(history, entry, "current")
    # Re-run the same publish: should replace, not duplicate.
    history = update_history(history, entry, "current")
    assert len(history["entries"]) == 1


def test_update_history_same_day_republish_accumulates():
    """Two real changes published on one UTC day share a date-stamped filename.

    The second publish must not evict the first's changes (the I Feel Love bug):
    the single entry for that date should carry the whole day's net change.
    """
    history = empty_history("current")
    # First publish of the day: diffed against last week's edition.
    first = {
        "generated_at": "2026-07-20T09:00:00+00:00",
        "manifest_filename": "sb-current-2026-07-20.manifest.json",
        "previous_manifest": "sb-current-2026-07-14.manifest.json",
        "previous_generated_at": "2026-07-14T00:00:00+00:00",
        "added": ["Macarena - Los Del Rio"],
        "removed": ["Ne Me Quitte Pas - Jacques Brel"],
        "added_count": 1,
        "removed_count": 1,
    }
    # Second publish, same day -> same filename, diffed against `first`'s manifest.
    second = {
        "generated_at": "2026-07-20T11:47:00+00:00",
        "manifest_filename": "sb-current-2026-07-20.manifest.json",
        "previous_manifest": "sb-current-2026-07-20.manifest.json",
        "previous_generated_at": "2026-07-20T09:00:00+00:00",
        "added": [],
        "removed": ["I Feel Love - Donna Summer"],
        "added_count": 0,
        "removed_count": 1,
    }
    history = update_history(history, first, "current")
    history = update_history(history, second, "current")

    assert len(history["entries"]) == 1
    entry = history["entries"][0]
    assert entry["added"] == ["Macarena - Los Del Rio"]
    assert entry["removed"] == [
        "I Feel Love - Donna Summer",
        "Ne Me Quitte Pas - Jacques Brel",
    ]
    assert entry["added_count"] == 1
    assert entry["removed_count"] == 2
    # Baseline is preserved from the first publish, identity from the second.
    assert entry["previous_manifest"] == "sb-current-2026-07-14.manifest.json"
    assert entry["previous_generated_at"] == "2026-07-14T00:00:00+00:00"
    assert entry["generated_at"] == "2026-07-20T11:47:00+00:00"


def test_update_history_same_day_republish_is_idempotent_on_retry():
    """Re-applying the same chained step (e.g. a workflow retry) is a no-op."""
    history = empty_history("current")
    first = {
        "manifest_filename": "sb-2026-07-20.manifest.json",
        "previous_manifest": "sb-2026-07-14.manifest.json",
        "added": ["A"],
        "removed": ["B"],
    }
    second = {
        "manifest_filename": "sb-2026-07-20.manifest.json",
        "previous_manifest": "sb-2026-07-20.manifest.json",
        "added": [],
        "removed": ["C"],
    }
    history = update_history(history, first, "current")
    history = update_history(history, second, "current")
    once = history["entries"][0]
    # The chained step arrives again (retry before latest.json advanced).
    history = update_history(history, second, "current")
    assert len(history["entries"]) == 1
    assert history["entries"][0]["added"] == once["added"]
    assert history["entries"][0]["removed"] == once["removed"]


def test_compose_entries_cancels_reverted_songs():
    base = {
        "manifest_filename": "day.json",
        "previous_manifest": "prev.json",
        "added": ["Keep - X", "Fleeting - Y"],
        "removed": ["Gone - Z", "Boomerang - W"],
    }
    step = {
        "manifest_filename": "day.json",
        "previous_manifest": "day.json",
        "added": ["Boomerang - W"],  # re-added -> cancels base's removal
        "removed": ["Fleeting - Y"],  # removed again -> cancels base's addition
    }
    composed = compose_entries(base, step)
    assert composed["added"] == ["Keep - X"]
    assert composed["removed"] == ["Gone - Z"]
    assert composed["previous_manifest"] == "prev.json"


def test_update_history_caps_entries():
    history = empty_history("current")
    for i in range(10):
        history = update_history(
            history, {"manifest_filename": f"m{i}.json"}, "current", max_entries=3
        )
    assert len(history["entries"]) == 3
    assert history["entries"][0]["manifest_filename"] == "m9.json"


def test_update_history_starts_fresh_when_existing_none():
    history = update_history(None, {"manifest_filename": "m.json"}, "current")
    assert history["edition"] == "current"
    assert len(history["entries"]) == 1


def test_short_key_matches_full_and_shortened_titles():
    # Full manifest name and its TOC-shortened render collapse to one key.
    full = "Crocodile Rock (Radio Edit) - Elton John"
    rendered = "Crocodile Rock - Elton John"  # as the TOC would show it
    assert short_key(full, max_length=52) == short_key(rendered, max_length=52)


def test_short_key_casefolds_and_strips_marker():
    assert short_key("Hey Jude - The Beatles*") == short_key("hey jude - the beatles")


def test_diff_keyed_uses_keys_but_returns_labels():
    new = {"a": "Song A - Artist", "b": "Song B - Artist"}
    old = {"a": "Song A - Artist", "c": "Song C - Artist"}
    added, removed = diff_keyed(new, old)
    assert added == ["Song B - Artist"]
    assert removed == ["Song C - Artist"]


def test_canon_strips_decorations_and_versions():
    assert canon("Crocodile Rock (Radio Edit) - Elton John*") == canon(
        "crocodile rock - elton john"
    )
    assert canon("Merry Christmas (I Don't Want to Fight...") == canon(
        "Merry Christmas (I Don't Want to Fight"
    )


_VOCAB = build_vocabulary(
    [
        "Merry Christmas (I Don't Want to Fight Tonight) - Ramones",
        "Happy Xmas (War is Over) - John Lennon, Yoko Ono",
        "Time Warp - Little Nell, Patricia Quinn, Richard O'Brien",
    ]
)


def test_resolve_truncated_title_to_full_catalogue_name():
    assert (
        resolve("Merry Christmas (I Don't Want to Fight", _VOCAB)
        == "Merry Christmas (I Don't Want to Fight Tonight) - Ramones"
    )


def test_resolve_glued_page_number_title():
    # The clean catalogue name is a prefix of the junk-suffixed TOC string.
    assert (
        resolve("Happy Xmas (War is Over) - John Lennon, Yoko Ono104", _VOCAB)
        == "Happy Xmas (War is Over) - John Lennon, Yoko Ono"
    )


def test_resolve_returns_none_for_non_catalogue_song():
    assert resolve("Some Forgotten B-Side - Nobody At All", _VOCAB) is None


def _pub(date, source, filename, songs):
    return {"date": date, "source": source, "filename": filename, "songs": songs}


def test_build_timeline_no_churn_across_drifting_renders():
    """The same songs rendered full / truncated / truncated-shorter across
    publishes resolve to one catalogue name each -> no spurious add/remove."""

    def songs(titles):
        out = {}
        for t in titles:
            r = resolve(t, _VOCAB) or t
            out[canon(r)] = r
        return out

    full = [
        "Merry Christmas (I Don't Want to Fight Tonight) - Ramones",
        "Time Warp - Little Nell, Patricia Quinn, Richard O'Brien",
    ]
    truncated = [
        "Merry Christmas (I Don't Want to Fight Tonight)",
        "Time Warp - Little Nell, Patricia Quinn, Richard",
    ]
    shorter = [
        "Merry Christmas (I Don't Want to Fight",
        "Time Warp - Little Nell, Patricia Quinn,",
    ]
    publishes = [
        _pub("2025-09-27", "toc-page", "a.pdf", songs(full)),
        _pub("2025-10-07", "toc-page", "b.pdf", songs(truncated)),
        _pub("2025-10-27", "toc-page", "c.pdf", songs(shorter)),
    ]
    history = build_timeline(publishes, "complete")
    assert history["entries"] == []  # stable set despite drifting renders


def test_build_timeline_orders_diffs_and_tags_source():
    publishes = [
        _pub("2025-09-27", "toc-page", "old.pdf", {"a": "A - X", "b": "B - Y"}),
        # New era, same two songs but full-name labels -> no spurious diff.
        _pub("2026-02-06", "manifest", "m1.json", {"a": "A - X (Mono)", "b": "B - Y"}),
        _pub("2026-06-09", "manifest", "m2.json", {"a": "A - X (Mono)", "c": "C - Z"}),
    ]
    history = build_timeline(publishes, "current")
    assert history["edition"] == "current"
    # Only the 09-27->02-06 boundary is a no-op; one real change recorded.
    assert len(history["entries"]) == 1
    entry = history["entries"][0]
    assert entry["date"] == "2026-06-09"
    assert entry["source"] == "manifest"
    assert entry["added"] == ["C - Z"]
    assert entry["removed"] == ["B - Y"]
    assert entry["previous_filename"] == "m1.json"


def test_build_timeline_newest_first_and_capped():
    publishes = [
        _pub("2026-01-01", "toc-page", "p0.pdf", {"a": "A - X"}),
        _pub("2026-01-02", "toc-page", "p1.pdf", {"a": "A - X", "b": "B - Y"}),
        _pub("2026-01-03", "toc-page", "p2.pdf", {"b": "B - Y"}),
    ]
    history = build_timeline(publishes, "current", max_entries=1)
    assert len(history["entries"]) == 1
    assert history["entries"][0]["date"] == "2026-01-03"  # newest kept


def test_backfill_history_filters_sorts_and_diffs():
    manifests = [
        # Out of order on purpose; sorted by generated_at ascending.
        (
            "c-0602.manifest.json",
            _manifest(["A", "B"], "2026-06-02T00:00:00+00:00", "current"),
        ),
        (
            "c-0526.manifest.json",
            _manifest(["A"], "2026-05-26T00:00:00+00:00", "current"),
        ),
        (
            "c-0609.manifest.json",
            _manifest(["A", "C"], "2026-06-09T00:00:00+00:00", "current"),
        ),
        # No-op republish (same songs as 0609, later) -> skipped.
        (
            "c-0609b.manifest.json",
            _manifest(["C", "A"], "2026-06-09T09:00:00+00:00", "current"),
        ),
        # Stray manifest for a different edition -> excluded.
        (
            "complete.manifest.json",
            _manifest(["X"], "2026-06-03T00:00:00+00:00", "complete"),
        ),
    ]
    history = backfill_history(manifests, "current")
    # 0526 is first publish (no previous) -> no entry. 0602 and 0609 each add one.
    assert [e["manifest_filename"] for e in history["entries"]] == [
        "c-0609.manifest.json",
        "c-0602.manifest.json",
    ]
    latest = history["entries"][0]
    assert latest["added"] == ["C"]
    assert latest["removed"] == ["B"]
    assert latest["previous_manifest"] == "c-0602.manifest.json"
