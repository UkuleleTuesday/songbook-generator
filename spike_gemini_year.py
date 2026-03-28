# /// script
# requires-python = ">=3.12"
# dependencies = ["google-genai"]
#
# [[tool.uv.index]]
# url = "https://pypi.org/simple"
# default = true
# ///
"""Spike: use Gemini + Google Search grounding to look up song release year."""

from google import genai
from google.genai import types

client = genai.Client(
    vertexai=True, project="songbook-generator", location="us-central1"
)

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
        contents=f'What year was "{song}" by {artist} originally released? Reply with only the 4-digit year, or "unknown" if you are not sure.',
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    print(f"{song} - {artist}: {response.text.strip()}")
