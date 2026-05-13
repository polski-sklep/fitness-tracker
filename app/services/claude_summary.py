import json
import logging
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models import CyclingEffort, Exercise, Session, StrengthSet, Summary

logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return super().default(obj)


SUMMARY_PROMPT = """You are reviewing one week of training data for a single user. Be blunt and specific. No filler.
Telegram renders **bold** but NOT # or ## or ### headers. Use ONLY **bold** for emphasis. Section titles should be bolded plain text on their own line, not Markdown headers.
Power Index is a dimensionless score where 100 is the user's median. NEVER call it watts. NEVER conflate it with cycling power output.
Different exercise classes operate at different absolute loads. Biceps curls at 25 kg and back rows at 80 kg are not directly comparable — never frame one as 'weak relative to' the other.
Use dual-register language: open each section with a plain-English headline sentence anyone could understand, then provide the technical detail in the following sentences. Example: 'Push day went well — 141 Index, well above your median 100.' Not: 'Upper push session exhibited 41% Index elevation over baseline.'
The user has 19 weeks of training history. They are not a beginner. Recommendations must respect their actual peak lifts. If suggesting an exercise, suggest a working weight derived from their seed peak e1RM, not a beginner placeholder.
Generate exactly one actionable recommendation, not multiple. If everything looks fine, say 'No change recommended — keep training the same way.'
Output format: opening paragraph (plain English summary of the week), then 3 bolded sections in this order: Strength, Cycling, Recommendation. No other sections. No sensitivity section unless something was actually flagged.
Length target: 250-300 words. Hard cap: 400 words.

FORMAT REQUIREMENTS:
- Opening paragraph: prose, no bullets, plain English.
- **Strength** section: brief prose framing (1 sentence per session describing how it went), followed by bullet points listing the specific lifts that matter. Use Telegram-compatible bullet character '•' (not '-' or '*'). Bold the exercise name and load. Example format:

Push day on May 5 was your standout session.
• **Flat barbell bench**: **48 kg** × 15 reps matched your 72 kg e1RM peak
• **Machine chest press**: **80 kg** × 10 reps close to your 112 kg lifetime best
• **Cable tricep pushdown**: **25 kg** × 12 hit your 37.5 kg peak

- **Cycling** section: prose only, no bullets. Two-three sentences.
- **Recommendation** section: prose only, no bullets. One clear directive.

- For lift bullets, always bold the exercise name and bold the load number with kg unit. Example: **Flat barbell bench**: **48 kg** × 15 reps
- Limit bullets to 3-5 per session (the most informative lifts only, not every single exercise logged).
- Use display names, not canonical names. Do not output underscores in session names or exercise names.

Use only the provided data. Do not infer unprovided readiness, fatigue, sensitivity, quality, wattage, or loads.
"""


def render_training_block(db: DbSession, start: date, end: date) -> str:
    sessions = (
        db.query(Session)
        .filter(Session.started_at >= start, Session.started_at < end, Session.deleted_at.is_(None))
        .order_by(Session.started_at)
        .all()
    )
    lifetime_peaks = _lifetime_peak_e1rm_by_exercise(db)
    payload = {
        "date_range": {
            "week_start_iso": start.isoformat(),
            "week_end_iso": (end - timedelta(days=1)).isoformat(),
            "query_end_exclusive_iso": end.isoformat(),
        },
        "history_context": {
            "history_length_weeks": 19,
            "median_session_power_index_baseline": 100,
            "power_index_units": "dimensionless score; never watts",
            "total_power_units": "dimensionless raw training-load points; never watts",
        },
        "lifetime_peak_e1rm_by_exercise": lifetime_peaks,
        "sessions": [],
    }
    for session in sessions:
        session_payload = {
            "date": session.started_at.date().isoformat(),
            "session_type": str(session.session_type),
            "total_power": _num(session.total_power),
            "index_vs_median": _num(session.index_vs_median),
            "readiness": session.readiness,
            "fatigue": session.fatigue,
            "sensitivity": session.sensitivity,
            "quality": session.quality,
            "time_minutes": session.time_minutes,
            "exercises": _strength_exercises_for_session(session),
            "cycling_rides": [
                {
                    "date": session.started_at.date().isoformat(),
                    "duration_min": effort.duration_min,
                    "distance_km": _num(effort.distance_km),
                    "kcal": effort.kcal,
                    "avg_watts": effort.avg_watts,
                    "max_watts": effort.max_watts,
                }
                for effort in session.cycling_efforts
            ],
        }
        for exercise_payload in session_payload["exercises"]:
            exercise_payload["peak_e1rm_lifetime"] = lifetime_peaks.get(exercise_payload["canonical_name"])
        payload["sessions"].append(session_payload)
    return json.dumps(payload, cls=DecimalEncoder, indent=2, sort_keys=True)


async def generate_weekly_summary(db: DbSession, start: date, end: date) -> Summary:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    body = render_training_block(db, start, end)
    message = await client.messages.create(
        model=settings.claude_model,
        max_tokens=1200,
        temperature=0,
        system=SUMMARY_PROMPT,
        messages=[{"role": "user", "content": body}],
    )
    markdown = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    markdown, warnings = postprocess_summary(markdown)
    for warning in warnings:
        logger.warning("Claude weekly summary sanity warning: %s", warning)
    if warnings:
        markdown = "[REVIEW NEEDED]\n" + markdown
    summary = Summary(period_start=start, period_end=end, body_md=markdown)
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


def _lifetime_peak_e1rm_by_exercise(db: DbSession) -> dict[str, float | None]:
    live_peaks = (
        db.query(
            StrengthSet.exercise_id.label("exercise_id"),
            func.max(StrengthSet.est_1rm).label("peak"),
        )
        .join(Session, Session.id == StrengthSet.session_id)
        .filter(Session.deleted_at.is_(None))
        .group_by(StrengthSet.exercise_id)
        .subquery()
    )
    rows = (
        db.query(Exercise, live_peaks.c.peak)
        .outerjoin(live_peaks, live_peaks.c.exercise_id == Exercise.id)
        .order_by(Exercise.name)
        .all()
    )
    peaks: dict[str, float | None] = {}
    for exercise, observed_peak in rows:
        seed_peak = _num(exercise.peak_e1rm_seed)
        peak = _num(observed_peak)
        if peak is None:
            peak = seed_peak
        elif seed_peak is not None:
            peak = max(peak, seed_peak)
        peaks[exercise.name] = peak
    return peaks


def _strength_exercises_for_session(session: Session) -> list[dict]:
    grouped: dict[Exercise, list[StrengthSet]] = defaultdict(list)
    for strength_set in session.strength_sets:
        grouped[strength_set.exercise].append(strength_set)
    exercises = []
    for exercise, sets in sorted(grouped.items(), key=lambda item: item[0].name):
        exercises.append(
            {
                "canonical_name": exercise.name,
                "display_name": exercise.display_name,
                "exercise_class": str(exercise.exercise_class) if exercise.exercise_class else None,
                "peak_e1rm_seed": _num(exercise.peak_e1rm_seed),
                "sets": [
                    {
                        "set_index": strength_set.set_index,
                        "reps": strength_set.reps,
                        "weight_kg": _num(strength_set.weight_kg),
                        "rir": strength_set.rir,
                        "local_sensitivity": str(strength_set.local_sensitivity),
                        "est_1rm": _num(strength_set.est_1rm),
                        "exercise_power": _num(strength_set.exercise_power),
                    }
                    for strength_set in sorted(sets, key=lambda item: item.set_index)
                ],
            }
        )
    return exercises


def postprocess_summary(markdown: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if "###" in markdown or "##" in markdown:
        warnings.append("summary contained Markdown header hashes; stripped # characters")
        markdown = markdown.replace("#", "")
    strength_section = _section_between(markdown, "Strength", "Cycling")
    if "W " in strength_section or "watts" in strength_section.lower():
        warnings.append("strength section may conflate Power Index with watts")
    forbidden_patterns = [
        ("goblet squats", "summary mentioned goblet squats"),
        ("machine ohp beginner alternatives", "summary mentioned machine OHP beginner alternatives"),
        ("establish a baseline", "summary used establish-a-baseline wording"),
    ]
    lowered = markdown.lower()
    for pattern, warning in forbidden_patterns:
        if pattern in lowered:
            warnings.append(warning)
    return markdown.strip(), warnings


def _section_between(markdown: str, start_heading: str, end_heading: str) -> str:
    pattern = rf"\*\*{re.escape(start_heading)}\*\*(.*?)(?:\*\*{re.escape(end_heading)}\*\*|$)"
    match = re.search(pattern, markdown, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def _num(value) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)
