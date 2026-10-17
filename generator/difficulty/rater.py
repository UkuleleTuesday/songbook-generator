"""Rate a song sheet's difficulty with an LLM, using the annotator rubric."""

import hashlib

from google.genai import types
from pydantic import BaseModel, Field

from ..tagupdater import tags
from ..tagupdater.tags import Context

DEFAULT_MODEL = "gemini-2.5-flash"
MIN_SCORE = 1.0
MAX_SCORE = 5.0

# First-draft prompt: the human annotator instructions, verbatim where possible.
SYSTEM_PROMPT = """\
# 1. The Goal and Your Role
Our goal is to create a new, reliable difficulty rating system for our entire \
ukulele songbook. Your expertise as a musician and teacher is critical.
The main purpose of this rating is to help players decide if they can pick up \
a song and play it live during our group sessions. Your rating should reflect \
how challenging a song is to follow along with on a first or second attempt.
Evaluate each song with fresh eyes. Ignore any prior ratings and your own \
familiarity with the song. Base your assessment on the song sheet alone.

# 2. The Rating Scale (1 to 5)
Half-points (e.g., 2.5) are acceptable if a song falls between two levels.
- 1: Absolute Beginner
  - Easy to follow along with on the first try.
  - Uses 2-3 very simple, one or two-finger open chords.
  - Simple, slow chord changes.
  - Basic, steady strumming pattern.
- 2: Confident Beginner
  - Can be played along with confidently after a quick scan.
  - Requires knowledge of most common open chords.
  - Chord changes are more frequent or involve slightly trickier transitions.
  - The rhythm is still straightforward.
- 3: Intermediate
  - Likely to have tricky sections that are hard to play correctly without \
prior practice.
  - Features at least one common barre chord.
  - May include slightly syncopated (swing) rhythms, dynamics changes \
(quiet/loud sections) or techniques like palm muting.
- 4: Advanced
  - Requires practice and/or regular attendance to be able to play along with \
the group.
  - Features multiple or frequent barre chords.
  - Requires challenging rhythms (e.g., swing, complex syncopation) or complex \
strumming techniques.
- 5: Expert
  - Very difficult to follow along with live; requires significant individual \
practice.
  - Contains unconventional or jazz chords, multiple advanced techniques, or \
structural complexities like shifts in tempo, key, or time signature.

# 3. Your Task: Evaluating the Sheet Music
Your rating must be based solely on the technical requirements presented on \
the song sheet. Judge the difficulty for a hypothetical player who has never \
seen this song before and is trying to play along with the group.

# 4. Guiding Principles for Your Rating
Use your expert intuition to form a holistic judgment. Frame your assessment \
around the live-play context and ask questions like:
- Play-Along Ability: Could a player at this level keep up with the group on \
their first or second attempt? How likely are they to get lost?
- Predictability: How easy is it to anticipate what's coming next? Is the \
structure simple and repetitive, or are there frequent, unexpected changes?
- Technical Hurdles: Are there specific chords or quick transitions that \
would cause someone to stop playing, even for a moment?
- Rhythmic Complexity: Is the rhythm simple and easy to feel, or is it \
complex and requiring concentration that makes it hard to read ahead?
- Cognitive Load: How much attention does the song demand? Does it have many \
different sections, key changes, or dynamic shifts that are hard to track \
while playing?

# 5. Final Reminders
- Be Objective: Base your rating on the sheet as written. Think about the \
general player, not your own personal skill level.
- Focus on the Minimum Skill: The rating should reflect the minimum skill \
level needed to successfully follow along live.

# Reading the song sheet
- Chords are in bold parentheses, e.g. **(G)**, placed where the change happens.
- ↓ after a chord means single down strums instead of the regular pattern.
- X is a chuck (percussive muted strum); N/C means no chord.
- Text in [square brackets] is a stage direction (e.g. [riff], [no ukes]).
- The line with the tempo and time signature also lists rhythm feels such as \
swing or gallop.
"""

USER_PROMPT_TEMPLATE = """\
Rate the difficulty of this song sheet.

Summary extracted from the sheet:
{summary}

Song sheet:
<<<
{sheet}
>>>
"""


class DifficultyRating(BaseModel):
    """Structured LLM answer; reasoning comes first so the score follows it."""

    reasoning: str = Field(
        description="Two to four sentences justifying the score against the rubric."
    )
    score: float = Field(
        description="Difficulty from 1 to 5; half points such as 2.5 are allowed."
    )


def prompt_hash() -> str:
    """Short, stable identifier of the prompt, used to tell runs apart."""
    digest = hashlib.sha256((SYSTEM_PROMPT + USER_PROMPT_TEMPLATE).encode())
    return digest.hexdigest()[:8]


def build_user_prompt(ctx: Context) -> str:
    """Renders the per-song prompt from the document and existing taggers."""
    chords = tags.chords(ctx)
    chord_list = chords.split(",") if chords else []
    summary = "\n".join(
        [
            f"- Chords ({len(chord_list)} distinct): {', '.join(chord_list) or 'none'}",
            f"- Features: {tags.features(ctx) or 'none'}",
            f"- Tempo (bpm): {tags.bpm(ctx) or 'unknown'}",
            f"- Time signature: {tags.time_signature(ctx) or 'unknown'}",
        ]
    )
    return USER_PROMPT_TEMPLATE.format(
        summary=summary, sheet=ctx.document.to_prompt_text()
    )


def rate_difficulty(ctx: Context, model: str = DEFAULT_MODEL) -> DifficultyRating:
    """
    Asks the LLM to rate the song in ``ctx.document``.

    Raises ``ValueError`` when the document is missing or the answer is not a
    valid score, so callers can record the failure instead of dropping it.
    """
    if ctx.document is None or ctx.genai_client is None:
        raise ValueError("A document and a genai client are required")

    response = ctx.genai_client.models.generate_content(
        model=model,
        contents=build_user_prompt(ctx),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            response_mime_type="application/json",
            response_schema=DifficultyRating,
        ),
    )
    if not response.text:
        raise ValueError("LLM returned an empty response")
    rating = DifficultyRating.model_validate_json(response.text)
    if not MIN_SCORE <= rating.score <= MAX_SCORE:
        raise ValueError(f"Score {rating.score} outside [{MIN_SCORE}, {MAX_SCORE}]")
    return rating
