"""
Seed canonical exercises from seed_exercises.json.

Usage:
    python scripts/seed.py
"""
import json
from pathlib import Path

from app.db import SessionLocal
from app.models import Exercise

SEED_FILE = Path(__file__).resolve().parents[1] / "seed_exercises.json"


def main() -> None:
    with open(SEED_FILE) as seed_file:
        seed = json.load(seed_file)

    db = SessionLocal()
    try:
        for item in seed["exercises"]:
            existing = db.query(Exercise).filter(Exercise.name == item["name"]).first()
            if existing:
                existing.display_name = item["display_name"]
                existing.modality = item["modality"]
                existing.exercise_class = item["exercise_class"]
                existing.ec_coefficient = item["ec_coefficient"]
                existing.muscle_groups = item["muscle_groups"]
                existing.peak_e1rm_seed = item.get("peak_e1rm_seed", 0)
                continue
            db.add(
                Exercise(
                    name=item["name"],
                    display_name=item["display_name"],
                    modality=item["modality"],
                    exercise_class=item["exercise_class"],
                    ec_coefficient=item["ec_coefficient"],
                    muscle_groups=item["muscle_groups"],
                    peak_e1rm_seed=item.get("peak_e1rm_seed", 0),
                )
            )
        db.commit()
        count = db.query(Exercise).count()
        print(f"Seeded {count} exercises")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

