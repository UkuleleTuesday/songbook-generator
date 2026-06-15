from .changelog import (
    backfill_history,
    build_entry,
    build_timeline,
    diff_keyed,
    diff_songs,
    empty_history,
    load_file_names,
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


def _pub(date, source, filename, songs):
    return {"date": date, "source": source, "filename": filename, "songs": songs}


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
