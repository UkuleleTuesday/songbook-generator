# /// script
# requires-python = ">=3.12"
# dependencies = ["google-genai", "pydantic"]
#
# [[tool.uv.index]]
# url = "https://pypi.org/simple"
# default = true
# ///
"""Spike: use Gemini structured output + Google Search to look up track duration."""

from typing import Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

client = genai.Client(vertexai=True, project="songbook-generator", location="us-central1")


class SongInfo(BaseModel):
    year: Optional[int] = Field(None, description="Original release year, e.g. 1977")
    duration_seconds: Optional[int] = Field(None, description="Track duration in seconds on original studio release")


TEST_CASES = [
    ("Psycho Killer", "Talking Heads"),
    ("Bohemian Rhapsody", "Queen"),
    ("Wonderwall", "Oasis"),
    ("Somewhere Over the Rainbow", "Israel Kamakawiwoʻole"),
    ("Nonexistent Song XYZ", "Fake Artist ABC"),
]

for song, artist in TEST_CASES:
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=f'Look up "{song}" by {artist}. Return the original release year and track duration.',
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            response_mime_type="application/json",
            response_schema=SongInfo,
        ),
    )
    info = SongInfo.model_validate_json(response.text)
    duration = f"{info.duration_seconds // 60}:{info.duration_seconds % 60:02d}" if info.duration_seconds else None
    print(f"{song} - {artist}: year={info.year}, duration={duration}")
