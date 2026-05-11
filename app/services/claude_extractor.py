import base64
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.schemas import ParsedSession

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a structured data extractor for a personal fitness tracker.
The user logs strength sessions and cycling rides.
Input is free-text or a screenshot of a workout note. Output is strict JSON.

Schema:
{
  "modality": "strength" | "cycling",
  "started_at": ISO8601 string or null,
  "session_type": "lower_core" | "upper_pull" | "upper_push" | "cycling" | "other",
  "readiness": 1-10 or null,
  "fatigue": 1-10 or null,
  "sensitivity": 1-10 or null,
  "quality": 1-10 or null,
  "time_minutes": integer or null,
  "notes": string or null,
  "exercises": [
    {
      "name": string,
      "exercise_class": "heavy_compound" | "bw_compound" | "db_compound" |
                        "machine_compound" | "isolation" | "corrective",
      "muscle_groups": [string, ...],
      "sets": [
        { "reps": int, "weight_kg": float, "rir": int|null,
          "local_sensitivity": "none"|"mild"|"moderate"|"severe",
          "local_sensitivity_note": string|null }
      ]
    }
  ],
  "cycling": {
    "distance_km": float|null,
    "kcal": int|null,
    "duration_min": int|null,
    "avg_hr": int|null
  } | null
}

Rules:
- For bodyweight movements (pull-ups, dips, push-ups), set weight_kg to the
  user's bodyweight, which is provided as a constant in the user message.
- Classify exercise_class accurately. Cable rows = machine_compound.
  Barbell back squat = heavy_compound. DB curl = isolation. Face pulls = corrective.
- session_type: infer from exercise mix. Squat/deadlift/lunges = lower_core.
  Pull-ups/rows/face pulls = upper_pull. Bench/OHP/dips = upper_push. Cycling rides = cycling.
- If a value is not present in the input, return null. Do not guess.
- Output strict JSON only. No commentary. No markdown fences.
- If the input contains multiple days or workouts, output a JSON array where each
  item follows the schema above. Keep each workout as its own object.

Spreadsheet screenshot example:
Columns are Day, Session, Block, Order, Item, Sets, Reps, Weight, Notes, Readiness, Fatigue,
Sensitivity, Quality, Time. Day and Session appear once per session and should be forward-filled.
Rows like Strength / Back squat / 3 / 5 / 140kg mean three identical sets of five at 140 kg.
"""


class ExtractionError(RuntimeError):
    pass


class ClaudeResponseTruncatedError(ExtractionError):
    pass


def _strip_json_fences(text: str) -> str:
    """Extract a JSON object or array from Claude's response.

    Handles responses with markdown fences, prose preamble, or unusual whitespace.
    Finds the first { or [ and returns everything through the matching closing brace.
    """
    if not text:
        return text

    text = text.strip()

    # Find the first { or [
    start_obj = text.find('{')
    start_arr = text.find('[')

    if start_obj == -1 and start_arr == -1:
        # No JSON structure found; return as-is and let json.loads raise a clear error
        return text

    # Pick whichever comes first
    if start_obj == -1:
        start = start_arr
        opener, closer = '[', ']'
    elif start_arr == -1:
        start = start_obj
        opener, closer = '{', '}'
    elif start_obj < start_arr:
        start = start_obj
        opener, closer = '{', '}'
    else:
        start = start_arr
        opener, closer = '[', ']'

    # Walk forward, tracking brace depth, respecting string quoting
    depth = 0
    in_string = False
    escape_next = False
    end = -1

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == '\\' and in_string:
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        # No matching close found; return from start to end of text and let json.loads error
        return text[start:]

    return text[start:end + 1]


def _coerce_sessions(payload) -> list[ParsedSession]:
    if isinstance(payload, list):
        return [ParsedSession.model_validate(item) for item in payload]
    if isinstance(payload, dict) and isinstance(payload.get("sessions"), list):
        return [ParsedSession.model_validate(item) for item in payload["sessions"]]
    return [ParsedSession.model_validate(payload)]


def _parse_responses(raw: str) -> list[ParsedSession]:
    cleaned = _strip_json_fences(raw)
    try:
        sessions = _coerce_sessions(json.loads(cleaned))
        if not sessions:
            raise ValueError("No sessions found in Claude response")
        return sessions
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ExtractionError(f"Claude extraction validation failed: {exc}\n\nRaw output:\n{raw}") from exc
    except ValueError as exc:
        raise ExtractionError(f"Claude extraction validation failed: {exc}\n\nRaw output:\n{raw}") from exc


def _parse_response(raw: str) -> ParsedSession:
    return _parse_responses(raw)[0]


async def extract_text(raw_text: str) -> ParsedSession:
    return (await extract_text_sessions(raw_text))[0]


async def extract_text_sessions(raw_text: str) -> list[ParsedSession]:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise ExtractionError("anthropic package is not installed") from exc

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.claude_model,
        max_tokens=8000,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"BODYWEIGHT_KG={settings.bodyweight_kg}\n\n{raw_text}"}],
    )
    raw = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    logger.info(f"Anthropic response stop_reason={message.stop_reason} usage={message.usage}")
    logger.error(f"CLAUDE_RAW_DEBUG (len={len(raw)}): {raw[:2000]}")
    if getattr(message, "stop_reason", None) == "max_tokens":
        logger.error(f"Claude response truncated. Stop reason: max_tokens. Length: {len(raw)} chars")
        raise ClaudeResponseTruncatedError(
            "Response was truncated by token limit. Try sending a shorter workout, or report this to the dev."
        )
    return _parse_responses(raw)


async def extract_image(image_path: str | Path, media_type: str = "image/png") -> ParsedSession:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise ExtractionError("anthropic package is not installed") from exc

    path = Path(image_path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model=settings.claude_model,
        max_tokens=8000,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"BODYWEIGHT_KG={settings.bodyweight_kg}"},
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}},
                ],
            }
        ],
    )
    raw = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    logger.info(f"Anthropic response stop_reason={message.stop_reason} usage={message.usage}")
    logger.error(f"CLAUDE_RAW_DEBUG (len={len(raw)}): {raw[:2000]}")
    if getattr(message, "stop_reason", None) == "max_tokens":
        logger.error(f"Claude response truncated. Stop reason: max_tokens. Length: {len(raw)} chars")
        raise ClaudeResponseTruncatedError(
            "Response was truncated by token limit. Try sending a shorter workout, or report this to the dev."
        )
    return _parse_response(raw)
