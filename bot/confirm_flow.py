from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.schemas import ParsedSession

PENDING: dict[int, list[ParsedSession]] = {}


def _format_load(weight_kg: float | None) -> str | None:
    if weight_kg is None:
        return None
    return f"{weight_kg:g}kg"


def _format_score(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f}".rstrip("0").rstrip(".")


def _format_date(parsed: ParsedSession) -> str:
    if parsed.started_at is None:
        return "no date"
    return parsed.started_at.date().isoformat()


def render_summary(parsed: ParsedSession | list[ParsedSession]) -> str:
    if isinstance(parsed, list):
        if len(parsed) == 1:
            return render_summary(parsed[0])
        sections = [f"Parsed {len(parsed)} separate sessions:"]
        for index, session in enumerate(parsed, start=1):
            sections.append(f"{index}. {render_summary(session)}")
        return "\n\n".join(sections)

    if parsed.modality == "cycling":
        cycling = parsed.cycling
        date_str = _format_date(parsed)
        duration = parsed.time_minutes or (cycling.duration_min if cycling else None)
        distance = cycling.distance_km if cycling else None
        kcal = cycling.kcal if cycling else None

        lines = [f"{date_str} · Cycling, {duration or '—'} min"]
        if distance is not None:
            lines.append(f"• Distance: {distance} km")
        if kcal is not None:
            lines.append(f"• Kcal: {kcal}")
        if cycling and cycling.avg_watts is not None:
            watts_str = f"• Watts: {cycling.avg_watts} avg"
            if cycling.max_watts is not None:
                watts_str += f" / {cycling.max_watts} max"
            lines.append(watts_str)
        if cycling and cycling.avg_rpm is not None:
            rpm_str = f"• RPM: {cycling.avg_rpm} avg"
            if cycling.max_rpm is not None:
                rpm_str += f" / {cycling.max_rpm} max"
            lines.append(rpm_str)
        return "\n".join(lines)

    lines = [
        f"{_format_date(parsed)} · {parsed.session_type}, {parsed.time_minutes or '—'} min, "
        f"R{_format_score(parsed.readiness)}/F{_format_score(parsed.fatigue)}/"
        f"S{_format_score(parsed.sensitivity)}/Q{_format_score(parsed.quality)}"
    ]
    for exercise in parsed.exercises:
        if not exercise.sets:
            continue
        first = exercise.sets[0]
        same_sets = all(
            item.reps == first.reps and item.weight_kg == first.weight_kg and item.rir == first.rir
            for item in exercise.sets
        )
        if same_sets:
            load = _format_load(first.weight_kg)
            detail = f"{len(exercise.sets)}×{first.reps}"
            if load:
                detail += f" @ {load}"
            if first.rir is not None:
                detail += f" (RIR {first.rir})"
        else:
            parts = []
            for item in exercise.sets:
                load = _format_load(item.weight_kg)
                parts.append(f"{item.reps}@{load}" if load else f"{item.reps}")
            detail = ", ".join(parts)
        lines.append(f"• {escape(exercise.name)}: {detail}")
    return "\n".join(lines)


def confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Save", callback_data="save"),
                InlineKeyboardButton("✏️ Edit", callback_data="edit"),
                InlineKeyboardButton("❌ Discard", callback_data="discard"),
            ]
        ]
    )
