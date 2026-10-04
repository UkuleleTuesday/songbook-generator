import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ..tagupdater.tags import Context, SongSheetGoogleDocument
from .rater import (
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    DifficultyRating,
    build_user_prompt,
    prompt_hash,
    rate_difficulty,
)

TEST_DATA_DIR = Path(__file__).parent.parent / "tagupdater" / "test_data"


@pytest.fixture
def love_me_do():
    with open(TEST_DATA_DIR / "love_me_do.json") as f:
        return SongSheetGoogleDocument(json=json.load(f))


def _ctx(document, response_text):
    client = Mock()
    client.models.generate_content.return_value.text = response_text
    return Context(file=None, document=document, genai_client=client)


def test_build_user_prompt_includes_summary_and_sheet(love_me_do):
    prompt = build_user_prompt(Context(file=None, document=love_me_do))

    assert "- Chords (4 distinct): G, C, D, D7" in prompt
    assert "- Features: swing" in prompt
    assert "- Tempo (bpm): 148" in prompt
    assert "- Time signature: 4/4" in prompt
    assert "**(G)**Love, love me do **(C)**" in prompt


def test_rate_difficulty_calls_llm_with_rubric_and_schema(love_me_do):
    ctx = _ctx(love_me_do, '{"reasoning": "Three open chords.", "score": 1.5}')

    rating = rate_difficulty(ctx)

    assert rating == DifficultyRating(reasoning="Three open chords.", score=1.5)
    kwargs = ctx.genai_client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["contents"] == build_user_prompt(ctx)
    assert kwargs["config"].system_instruction == SYSTEM_PROMPT
    assert kwargs["config"].response_schema is DifficultyRating
    assert kwargs["config"].temperature == 0


@pytest.mark.parametrize(
    "response_text",
    ['{"reasoning": "x", "score": 7}', '{"reasoning": "x", "score": 0.5}'],
)
def test_rate_difficulty_rejects_out_of_range_scores(love_me_do, response_text):
    with pytest.raises(ValueError, match="outside"):
        rate_difficulty(_ctx(love_me_do, response_text))


@pytest.mark.parametrize("response_text", ["not json", "", None])
def test_rate_difficulty_rejects_unparseable_responses(love_me_do, response_text):
    with pytest.raises(ValueError):
        rate_difficulty(_ctx(love_me_do, response_text))


def test_rate_difficulty_requires_document():
    with pytest.raises(ValueError, match="document"):
        rate_difficulty(Context(file=None, genai_client=Mock()))


def test_prompt_hash_is_short_and_stable():
    assert prompt_hash() == prompt_hash()
    assert len(prompt_hash()) == 8
