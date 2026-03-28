"""Spike: test MusicBrainz year lookup by song + artist."""

import requests

MB_API = "https://musicbrainz.org/ws/2"
HEADERS = {"User-Agent": "songbook-generator-spike/0.1 (spike test)"}


def get_year(song: str, artist: str) -> str | None:
    # Phase 1: release-group search — works well when song title matches album title
    resp = requests.get(
        f"{MB_API}/release-group",
        params={
            "query": f'release-group:"{song}" AND artist:"{artist}"',
            "fmt": "json",
            "limit": 5,
        },
        headers=HEADERS,
    )
    resp.raise_for_status()
    groups = resp.json().get("release-groups", [])

    # Only trust the top result. If it's a compilation (best-of, greatest hits),
    # fall through — don't reach for lower-scored results which may be wrong songs.
    if groups:
        top = groups[0]
        if "Compilation" not in top.get("secondary-types", []):
            date = top.get("first-release-date", "")
            if date:
                return date[:4]

    # Phase 2: fallback to recording search — searches track titles, not album titles.
    # Needed for covers/tracks where the album title doesn't match the song name.
    resp2 = requests.get(
        f"{MB_API}/recording",
        params={
            "query": f'recording:"{song}" AND artist:"{artist}"',
            "fmt": "json",
            "limit": 5,
        },
        headers=HEADERS,
    )
    resp2.raise_for_status()
    recordings = resp2.json().get("recordings", [])

    dates = []
    for recording in recordings:
        for release in recording.get("releases", []):
            date = release.get("date", "")
            if date:
                dates.append(date)

    if not dates:
        return None
    return sorted(dates)[0][:4]


TEST_CASES = [
    ("Psycho Killer", "Talking Heads"),
    ("Bohemian Rhapsody", "Queen"),
    ("Wonderwall", "Oasis"),
    ("Somewhere Over the Rainbow", "Israel Kamakawiwoʻole"),
    ("Nonexistent Song XYZ", "Fake Artist ABC"),
]

for song, artist in TEST_CASES:
    year = get_year(song, artist)
    print(f"{song} - {artist}: {year}")
