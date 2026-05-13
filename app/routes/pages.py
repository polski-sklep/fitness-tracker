import re
from html import escape
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession, joinedload

from app.db import get_db
from app.models import CyclingEffort, Exercise, Session, StrengthSet, Summary

router = APIRouter()

PROFILE_PATH = Path("profile/jacobkowalewski.txt")
PROFILE_DIR = Path("profile")
TEXT_DIR = Path("text")
BLANK_PROFILE_BODY = """# Personal Profile

Edit this file with anything the tracker or future prompts should know about you.

## Basics
- Name:
- Bodyweight:
- Time zone:

## Training Goals
- Primary goal:
- Secondary goals:
- Current focus:

## Constraints & Sensitivities
- Injuries or sensitive joints:
- Exercises to avoid:
- Exercises to prioritize:

## Preferences
- Preferred session length:
- Preferred training split:
- Cardio preference:

## Notes for Coaching
- Motivation style:
- Recovery signals to watch:
- Other context:
"""


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: DbSession = Depends(get_db)) -> HTMLResponse:
    week_start = datetime.now() - timedelta(days=7)
    sessions = (
        db.query(Session)
        .filter(Session.deleted_at.is_(None))
        .order_by(Session.started_at.desc())
        .limit(10)
        .all()
    )
    weekly_sessions = db.query(func.count(Session.id)).filter(Session.started_at >= week_start, Session.deleted_at.is_(None)).scalar()
    weekly_index = db.query(func.avg(Session.index_vs_median)).filter(Session.started_at >= week_start, Session.deleted_at.is_(None)).scalar()
    weekly_km = (
        db.query(func.sum(CyclingEffort.distance_km))
        .join(Session, Session.id == CyclingEffort.session_id)
        .filter(Session.started_at >= week_start, Session.deleted_at.is_(None))
        .scalar()
    )
    weekly_kcal = (
        db.query(func.sum(CyclingEffort.kcal))
        .join(Session, Session.id == CyclingEffort.session_id)
        .filter(Session.started_at >= week_start, Session.deleted_at.is_(None))
        .scalar()
    )
    latest_summary = db.query(Summary).order_by(Summary.generated_at.desc()).first()
    heatmap = _muscle_heatmap(db)
    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "sessions": sessions,
            "weekly_sessions": weekly_sessions or 0,
            "weekly_index": round(float(weekly_index or 0), 1),
            "weekly_km": round(float(weekly_km or 0), 1),
            "weekly_kcal": int(weekly_kcal or 0),
            "latest_summary": latest_summary,
            "heatmap": heatmap,
            "profile_options": _profile_options(),
            "text_documents": _document_list(TEXT_DIR),
        },
    )


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
def session_detail(session_id: int, request: Request, db: DbSession = Depends(get_db)) -> HTMLResponse:
    session = (
        db.query(Session)
        .options(joinedload(Session.strength_sets).joinedload(StrengthSet.exercise), joinedload(Session.cycling_efforts))
        .filter(Session.id == session_id, Session.deleted_at.is_(None))
        .first()
    )
    if not session:
        raise HTTPException(status_code=404)
    grouped: dict[Exercise, list[StrengthSet]] = {}
    for strength_set in sorted(session.strength_sets, key=lambda item: (item.exercise.display_name, item.set_index)):
        grouped.setdefault(strength_set.exercise, []).append(strength_set)
    return request.app.state.templates.TemplateResponse(request, "session_detail.html", {"session": session, "grouped": grouped})


@router.get("/exercises/{exercise_id}", response_class=HTMLResponse)
def exercise_detail(exercise_id: int, request: Request, db: DbSession = Depends(get_db)) -> HTMLResponse:
    exercise = db.get(Exercise, exercise_id)
    if not exercise:
        raise HTTPException(status_code=404)
    sets = (
        db.query(StrengthSet)
        .join(Session, Session.id == StrengthSet.session_id)
        .options(joinedload(StrengthSet.session))
        .filter(StrengthSet.exercise_id == exercise_id, Session.deleted_at.is_(None))
        .order_by(StrengthSet.created_at.desc())
        .limit(20)
        .all()
    )
    return request.app.state.templates.TemplateResponse(request, "exercise_detail.html", {"exercise": exercise, "sets": sets})


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request) -> HTMLResponse:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PROFILE_PATH.exists():
        PROFILE_PATH.write_text(BLANK_PROFILE_BODY)
    return request.app.state.templates.TemplateResponse(
        request,
        "document.html",
        {"title": "Jacob Kowalewski", "body_html": _render_document(PROFILE_PATH), "download_url": None},
    )


@router.get("/profile/edit", response_class=HTMLResponse)
def edit_profile_page(request: Request) -> HTMLResponse:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = PROFILE_PATH.read_text() if PROFILE_PATH.exists() else BLANK_PROFILE_BODY
    return request.app.state.templates.TemplateResponse(
        request,
        "profile.html",
        {"body": body},
    )


@router.post("/profile/edit")
def save_profile(body: str = Form(...)) -> RedirectResponse:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(body)
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile")
def save_profile_legacy(body: str = Form(...)) -> RedirectResponse:
    return save_profile(body)


@router.get("/profile/download")
def download_profile() -> Response:
    return _download_blank_profile()


@router.get("/profile/blank-profile/download")
def download_blank_profile() -> Response:
    return _download_blank_profile()


@router.get("/text/{slug}", response_class=HTMLResponse)
def read_text_document(slug: str, request: Request) -> HTMLResponse:
    title, path = _document_by_slug(TEXT_DIR, slug)
    return request.app.state.templates.TemplateResponse(
        request,
        "document.html",
        {"title": title, "body_html": _render_document(path), "download_url": f"/text/{slug}/download"},
    )


@router.get("/text/{slug}/download")
def download_text_document(slug: str) -> FileResponse:
    title, path = _document_by_slug(TEXT_DIR, slug)
    return FileResponse(path, filename=path.name)


@router.get("/profile/{slug}", response_class=HTMLResponse)
def read_profile_document(slug: str, request: Request) -> HTMLResponse:
    title, path = _document_by_slug(PROFILE_DIR, slug)
    return request.app.state.templates.TemplateResponse(
        request,
        "document.html",
        {"title": title, "body_html": _render_document(path), "download_url": None},
    )


def _document_list(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    paths = [item for item in directory.iterdir() if item.is_file() and not item.name.startswith(".")]
    preferred_by_stem: dict[str, Path] = {}
    extension_rank = {".md": 0, ".txt": 1, ".rtf": 2}
    for path in paths:
        current = preferred_by_stem.get(path.stem)
        if current is None or extension_rank.get(path.suffix.lower(), 99) < extension_rank.get(current.suffix.lower(), 99):
            preferred_by_stem[path.stem] = path
    return [
        {"title": _document_title(path), "slug": _document_slug(path), "path": path}
        for path in sorted(preferred_by_stem.values(), key=lambda item: item.name)
    ]


def _profile_options() -> list[dict]:
    return [
        {
            "title": "Jacob Kowalewski",
            "view_url": "/profile",
            "edit_url": "/profile/edit",
        },
        {
            "title": "Blank Profile",
            "download_url": "/profile/blank-profile/download",
        },
    ]


def _download_blank_profile() -> Response:
    return Response(
        BLANK_PROFILE_BODY,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="blank_profile.md"'},
    )


def _document_by_slug(directory: Path, slug: str) -> tuple[str, Path]:
    for document in _document_list(directory):
        if document["slug"] == slug:
            return document["title"], document["path"]
    raise HTTPException(status_code=404)


def _document_slug(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")


def _document_title(path: Path) -> str:
    if path.stem == "jacobkowalewski":
        return "Jacob Kowalewski"
    if path.name == "profile.md":
        return "Blank Profile"
    return path.stem.replace("_", " ").replace("-", " ").title()


def _render_document(path: Path) -> str:
    return _markdown_to_html(_read_document(path))


def _read_document(path: Path) -> str:
    raw = path.read_text(errors="ignore")
    if path.suffix.lower() == ".rtf":
        return _rtf_to_text(raw)
    return raw


def _markdown_to_html(markdown: str) -> str:
    html: list[str] = []
    in_list = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                html.append("</ul>")
                in_list = False
            continue
        if line in {"---", "***", "___", "—", "–", "⸻"}:
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append("<hr>")
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            if in_list:
                html.append("</ul>")
                in_list = False
            level = min(len(heading.group(1)) + 1, 4)
            html.append(f"<h{level}>{_render_inline(heading.group(2))}</h{level}>")
            continue
        plain_heading = _plain_text_heading_level(line)
        if plain_heading:
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h{plain_heading}>{_render_inline(line)}</h{plain_heading}>")
            continue
        bullet = re.match(r"^(?:[-*•]\s*|\d+\.\s+)(.+)$", line)
        if bullet:
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_render_inline(bullet.group(1))}</li>")
            continue
        if in_list:
            html.append("</ul>")
            in_list = False
        key_value = re.match(r"^([A-Z][A-Za-z /&-]{1,42}:)\s+(.+)$", line)
        if key_value:
            html.append(f"<p><strong>{escape(key_value.group(1))}</strong> {_render_inline(key_value.group(2))}</p>")
        else:
            html.append(f"<p>{_render_inline(line)}</p>")
    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def _plain_text_heading_level(line: str) -> int | None:
    if len(line) > 72:
        return None
    if ":" in line or re.search(r"[.;!?]$", line):
        return None
    if re.match(r"^[A-Z][A-Z\s/]+—?$", line):
        return 2
    if re.match(r"^\d+\.\s+[A-Z]", line):
        return 3
    if line[:1].isupper() and not re.search(r"[,.]", line):
        words = line.split()
        if 1 <= len(words) <= 5:
            return 3
    return None


def _render_inline(text: str) -> str:
    placeholders: list[str] = []

    def stash(value: str) -> str:
        placeholders.append(value)
        return f"@@HTML{len(placeholders) - 1}@@"

    text = re.sub(
        r"\*\*\[([^\]]+)\]\(([^)]+)\)\*\*",
        lambda match: stash(
            f'<strong><a href="{escape(match.group(2), quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{escape(match.group(1))}</a></strong>"
        ),
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: stash(
            f'<a href="{escape(match.group(2), quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{escape(match.group(1))}</a>"
        ),
        text,
    )
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    for index, value in enumerate(placeholders):
        text = text.replace(f"@@HTML{index}@@", value)
    return text


def _rtf_to_text(raw: str) -> str:
    destinations = {
        "fonttbl",
        "colortbl",
        "datastore",
        "expandedcolortbl",
        "filetbl",
        "footer",
        "header",
        "info",
        "listoverridetable",
        "listtable",
        "object",
        "pict",
        "stylesheet",
        "themedata",
        "xmlnstbl",
    }
    text: list[str] = []
    stack: list[bool] = [False]
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "{":
            stack.append(stack[-1])
            index += 1
            continue
        if char == "}":
            if len(stack) > 1:
                stack.pop()
            index += 1
            continue
        if char != "\\":
            if not stack[-1] and char not in "\r\n":
                text.append(char)
            index += 1
            continue

        index += 1
        if index >= len(raw):
            break
        control = raw[index]
        if control in "{}\\":
            if not stack[-1]:
                text.append(control)
            index += 1
            continue
        if control == "'":
            hex_value = raw[index + 1 : index + 3]
            if not stack[-1] and len(hex_value) == 2:
                try:
                    text.append(bytes.fromhex(hex_value).decode("cp1252"))
                except UnicodeDecodeError:
                    pass
            index += 3
            continue
        if control == "*":
            stack[-1] = True
            index += 1
            continue
        match = re.match(r"([a-zA-Z]+)(-?\d+)? ?", raw[index:])
        if not match:
            if not stack[-1] and control == "~":
                text.append(" ")
            index += 1
            continue
        word, parameter = match.group(1), match.group(2)
        index += len(match.group(0))
        if word in destinations:
            stack[-1] = True
            continue
        if stack[-1]:
            continue
        if word in {"par", "line"}:
            text.append("\n")
        elif word == "tab":
            text.append("\t")
        elif word == "bullet":
            text.append("•")
        elif word == "emdash":
            text.append("—")
        elif word == "endash":
            text.append("–")
        elif word == "u" and parameter:
            codepoint = int(parameter)
            if codepoint < 0:
                codepoint += 65536
            text.append(chr(codepoint))
    cleaned = "".join(text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"^\s+", "", cleaned)
    return cleaned.strip()


def _muscle_heatmap(db: DbSession) -> dict:
    groups = ["chest", "back", "quads", "hamstrings", "glutes", "shoulders", "biceps", "triceps", "core", "calves"]
    weeks = [(datetime.now() - timedelta(weeks=week)).isocalendar()[:2] for week in range(11, -1, -1)]
    values = {group: {week: 0.0 for week in weeks} for group in groups}
    rows = (
        db.query(Session.started_at, Exercise.muscle_groups, func.sum(StrengthSet.exercise_power))
        .join(StrengthSet, StrengthSet.session_id == Session.id)
        .join(Exercise, Exercise.id == StrengthSet.exercise_id)
        .filter(Session.started_at >= datetime.now() - timedelta(weeks=12), Session.deleted_at.is_(None))
        .group_by(Session.started_at, Exercise.muscle_groups)
        .all()
    )
    for started_at, muscle_groups, power in rows:
        week_key = started_at.isocalendar()[:2]
        for group in muscle_groups or []:
            if group in values and week_key in values[group]:
                values[group][week_key] += float(power or 0)
    global_max = max((value for week_values in values.values() for value in week_values.values()), default=0) or 1
    week_labels = {week: f"{date.fromisocalendar(week[0], week[1], 1).strftime('%b')} {date.fromisocalendar(week[0], week[1], 1).day}" for week in weeks}
    colors = {
        group: {
            week: _heatmap_color(values[group][week], global_max)
            for week in weeks
        }
        for group in groups
    }
    return {"weeks": weeks, "week_labels": week_labels, "groups": groups, "values": values, "colors": colors}


def _heatmap_color(value: float, global_max: float) -> str:
    if value <= 0:
        return "rgb(13, 17, 23)"
    start = (13, 17, 23)
    end = (59, 130, 246)
    ratio = min(value / global_max, 1.0)
    red = round(start[0] + (end[0] - start[0]) * ratio)
    green = round(start[1] + (end[1] - start[1]) * ratio)
    blue = round(start[2] + (end[2] - start[2]) * ratio)
    return f"rgb({red}, {green}, {blue})"
