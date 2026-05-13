"""
Backfill historical cycling efforts from intensity-scale screenshots.

Usage:
    python scripts/backfill_cycling.py
"""
from datetime import date, datetime, time, timezone

from sqlalchemy import func

from app.db import SessionLocal
from app.models import CyclingEffort, Session, SessionType

RIDES = [
    {"date": date(2026, 1, 15), "duration_min": 44, "distance_km": 20.7, "kcal": 456, "avg_watts": 146, "max_watts": 748, "avg_rpm": 69},
    {"date": date(2026, 3, 6), "duration_min": 52, "distance_km": 23.8, "kcal": 524, "avg_watts": 137, "max_watts": 682, "avg_rpm": 71},
    {"date": date(2026, 4, 28), "duration_min": 46, "distance_km": 22.9, "kcal": 506, "avg_watts": 158, "max_watts": 579, "avg_rpm": 68},
    {"date": date(2026, 4, 30), "duration_min": 45, "distance_km": 22.7, "kcal": 501, "avg_watts": 160, "max_watts": 523, "avg_rpm": 73},
    {"date": date(2026, 5, 5), "duration_min": 49, "distance_km": 24.7, "kcal": 547, "avg_watts": 162, "max_watts": 572, "avg_rpm": 70},
    {"date": date(2026, 5, 7), "duration_min": 44, "distance_km": 21.8, "kcal": 460, "avg_watts": 144, "max_watts": 563, "avg_rpm": 78},
]


def cycling_effort_exists(db, ride_date: date) -> bool:
    return (
        db.query(CyclingEffort)
        .join(Session, Session.id == CyclingEffort.session_id)
        .filter(
            Session.session_type == SessionType.cycling,
            func.date(Session.started_at) == ride_date,
        )
        .first()
        is not None
    )


def main() -> None:
    db = SessionLocal()
    try:
        for ride in RIDES:
            ride_date = ride["date"]
            if cycling_effort_exists(db, ride_date):
                print(f"skipped {ride_date.isoformat()}")
                continue

            session = Session(
                started_at=datetime.combine(ride_date, time(hour=12), tzinfo=timezone.utc),
                session_type=SessionType.cycling,
                time_minutes=ride["duration_min"],
                notes="Backfilled from intensity-scale screenshots",
            )
            db.add(session)
            db.flush()
            db.add(
                CyclingEffort(
                    session_id=session.id,
                    distance_km=ride["distance_km"],
                    kcal=ride["kcal"],
                    duration_min=ride["duration_min"],
                    avg_hr=None,
                    avg_watts=ride["avg_watts"],
                    max_watts=ride["max_watts"],
                    avg_rpm=ride["avg_rpm"],
                    notes="Backfilled from intensity-scale screenshots",
                )
            )
            print(f"inserted {ride_date.isoformat()}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

