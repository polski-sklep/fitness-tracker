from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import get_db
from app.models import CyclingEffort, Exercise, RawInput, RawInputKind, Session, StrengthSet
from app.schemas import PersistSessionRequest, PersistSessionResponse, RawTextIngest
from app.services.claude_extractor import ExtractionError, extract_text
from app.services.persistence import create_session_from_payload

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/sessions", response_model=PersistSessionResponse)
def create_session(request: PersistSessionRequest, db: DbSession = Depends(get_db)) -> PersistSessionResponse:
    session, prs = create_session_from_payload(db, request.parsed, request.raw_input_id)
    db.commit()
    db.refresh(session)
    return PersistSessionResponse(id=session.id, total_power=session.total_power, index_vs_median=session.index_vs_median, prs=prs)


@router.post("/sessions/from_raw", response_model=PersistSessionResponse)
async def create_session_from_raw(request: RawTextIngest, db: DbSession = Depends(get_db)) -> PersistSessionResponse:
    raw_input = RawInput(kind=RawInputKind.text, raw_text=request.text, claude_model=settings.claude_model)
    db.add(raw_input)
    db.flush()
    try:
        parsed = await extract_text(request.text)
        session, prs = create_session_from_payload(db, parsed, raw_input.id)
    except ExtractionError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(session)
    return PersistSessionResponse(id=session.id, total_power=session.total_power, index_vs_median=session.index_vs_median, prs=prs)


@router.get("/chart/sessions")
def session_chart(db: DbSession = Depends(get_db)) -> dict:
    sessions = (
        db.query(Session)
        .filter(Session.deleted_at.is_(None), Session.index_vs_median.isnot(None))
        .order_by(Session.started_at)
        .all()
    )
    return {
        "labels": [session.started_at.date().isoformat() for session in sessions],
        "datasets": [
            {
                "label": "Index vs median",
                "data": [float(session.index_vs_median or 0) for session in sessions],
                "session_types": [session.session_type for session in sessions],
                "borderColor": "#22c55e",
            }
        ],
    }


@router.get("/chart/cycling")
def cycling_chart(db: DbSession = Depends(get_db)) -> dict:
    rows = (
        db.query(
            Session.started_at,
            CyclingEffort.distance_km,
            CyclingEffort.kcal,
            CyclingEffort.duration_min,
            CyclingEffort.avg_watts,
            CyclingEffort.max_watts,
            CyclingEffort.avg_rpm,
            CyclingEffort.max_rpm,
        )
        .join(CyclingEffort, CyclingEffort.session_id == Session.id)
        .filter(Session.deleted_at.is_(None))
        .order_by(Session.started_at)
        .all()
    )
    return {
        "labels": [row[0].date().isoformat() for row in rows],
        "datasets": [
            {"label": "Kcal", "data": [int(row[2] or 0) for row in rows], "borderColor": "#f97316", "backgroundColor": "rgba(251, 146, 60, 0.2)", "fill": True},
        ],
        "meta": [
            {
                "distance_km": float(row[1] or 0),
                "duration_min": int(row[3] or 0),
                "avg_watts": int(row[4] or 0),
                "max_watts": int(row[5] or 0),
                "avg_rpm": int(row[6] or 0),
                "max_rpm": int(row[7] or 0),
            }
            for row in rows
        ],
    }


@router.get("/chart/exercises/{exercise_id}")
def exercise_chart(exercise_id: int, db: DbSession = Depends(get_db)) -> dict:
    exercise = db.get(Exercise, exercise_id)
    if not exercise:
        raise HTTPException(status_code=404)
    rows = (
        db.query(Session.started_at, func.max(StrengthSet.exercise_power), func.max(StrengthSet.est_1rm))
        .join(StrengthSet, StrengthSet.session_id == Session.id)
        .filter(StrengthSet.exercise_id == exercise_id, Session.deleted_at.is_(None))
        .group_by(Session.started_at)
        .order_by(Session.started_at)
        .all()
    )
    return {
        "labels": [row[0].date().isoformat() for row in rows],
        "datasets": [
            {"label": "Exercise Power", "data": [float(row[1] or 0) for row in rows], "borderColor": "#22c55e"},
            {"label": "Peak e1RM", "data": [float(row[2] or 0) for row in rows], "borderColor": "#eab308"},
        ],
    }
