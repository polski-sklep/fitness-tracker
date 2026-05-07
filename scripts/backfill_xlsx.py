"""
Backfill historical training data from TrainerGPT_26_.xlsx into the fitness tracker DB.

Format assumptions (verified against the user's actual file):
- Sheet name: "2026"
- Header row at row index 1 (0-indexed); data starts row 2
- Columns: Day, Session, Block, Order, Item, Sets, Reps, Weight, Notes,
           Readiness, Fatigue, Sensitivity, Quality, Time
- Day and Session appear ONCE per session (top row); forward-fill required
- R/F/S/Q/Time appear ONCE per session (top row); forward-fill within Day group
- Weight column has formats: "40kg", "32.5kg", or non-numeric ("Kinesis Station Level 3")
- Bodyweight movements (pull-ups, dips) have NaN weight — substitute BODYWEIGHT_KG
- Block values: Warm-up, Activation, Core, Strength, Accessory, Cool-down, Cardio
- Only Block in {Strength, Accessory, Core} typically have parseable kg weights
- Notes column may contain "Failure" / "Until Failure" — historically NO RIR data

Usage:
    python scripts/backfill_xlsx.py path/to/TrainerGPT_26_.xlsx
"""
import sys
import re
import json
from pathlib import Path
from datetime import datetime

import pandas as pd

# These imports assume the script runs inside the app container with PYTHONPATH=/app
from app.db import SessionLocal
from app.models import Exercise, Session, StrengthSet
from app.services.power_score import (
    epley_e1rm, exercise_power, session_power, index_vs_median,
)
from app.services.session_classifier import classify_session_type

BODYWEIGHT_KG = 78
SEED_FILE = Path(__file__).parent.parent / "seed_exercises.json"


def parse_weight(raw):
    if raw is None or pd.isna(raw):
        return None
    m = re.match(r"^\s*(\d+\.?\d*)\s*kg", str(raw), re.IGNORECASE)
    return float(m.group(1)) if m else None


def parse_minutes(raw):
    if raw is None or pd.isna(raw):
        return None
    m = re.match(r"^\s*(\d+)\s*minutes?", str(raw), re.IGNORECASE)
    return int(m.group(1)) if m else None


def is_bodyweight_movement(item: str) -> bool:
    s = (item or "").lower()
    return any(k in s for k in (
        "pull up", "pull-up", "pullup",
        "dip", "push up", "push-up", "pushup",
        "chin up", "chinup",
    ))


def session_type_from_name(name: str) -> str:
    n = (name or "").lower()
    if "lower" in n:
        return "lower_core"
    if "pull" in n:
        return "upper_pull"
    if "push" in n:
        return "upper_push"
    if "cardio" in n or "cycling" in n:
        return "cycling"
    return "other"


def load_seed():
    with open(SEED_FILE) as f:
        seed = json.load(f)
    aliases = {k.lower(): v.lower() for k, v in seed["aliases"].items()}
    by_name = {e["name"]: e for e in seed["exercises"]}
    return aliases, by_name


def canonicalize(item: str, aliases: dict) -> str:
    key = (item or "").strip().lower()
    return aliases.get(key, key)


def ensure_exercise(db, canonical_name: str, by_name: dict):
    existing = db.query(Exercise).filter(Exercise.name == canonical_name).first()
    if existing:
        return existing

    seed_entry = by_name.get(canonical_name)
    if not seed_entry:
        # Unknown exercise — create a stub with safe defaults; manual cleanup later
        ex = Exercise(
            name=canonical_name,
            display_name=canonical_name.title(),
            modality="strength",
            exercise_class="machine_compound",
            ec_coefficient=0.85,
            muscle_groups=[],
        )
    else:
        ex = Exercise(
            name=seed_entry["name"],
            display_name=seed_entry["display_name"],
            modality=seed_entry["modality"],
            exercise_class=seed_entry["exercise_class"],
            ec_coefficient=seed_entry["ec_coefficient"],
            muscle_groups=seed_entry["muscle_groups"],
        )
    db.add(ex)
    db.flush()
    return ex


def main(xlsx_path: str):
    aliases, by_name = load_seed()

    df = pd.read_excel(xlsx_path, sheet_name="2026", header=1)
    df = df.drop(columns=[c for c in df.columns if str(c).startswith("Unnamed")])

    for c in ["Session", "Block", "Item", "Weight", "Notes", "Time"]:
        df[c] = df[c].astype(str).str.strip().replace({"nan": None, "None": None})

    df["Day"] = pd.to_datetime(df["Day"], errors="coerce").ffill()
    df["Session"] = df["Session"].ffill()

    for col in ["Readiness", "Fatigue", "Sensitivity", "Quality", "Time"]:
        df[col] = df.groupby("Day")[col].transform(lambda s: s.ffill().bfill())

    df["Sets"] = pd.to_numeric(df["Sets"], errors="coerce")
    df["Reps"] = pd.to_numeric(df["Reps"], errors="coerce")
    df["weight_kg"] = df["Weight"].apply(parse_weight)
    df["time_min"] = df["Time"].apply(parse_minutes)

    # Promote bodyweight movements to BODYWEIGHT_KG
    bw_mask = df["Item"].apply(is_bodyweight_movement) & df["weight_kg"].isna()
    df.loc[bw_mask, "weight_kg"] = BODYWEIGHT_KG

    # Keep only strength rows (have Sets, Reps, weight_kg)
    strength = df[
        df["Sets"].notna() & df["Reps"].notna() & df["weight_kg"].notna()
    ].copy()

    print(f"Parsed {len(strength)} strength entries across "
          f"{strength['Day'].nunique()} sessions")

    db = SessionLocal()
    try:
        for day, rows in strength.groupby("Day"):
            head = rows.iloc[0]
            session_type = session_type_from_name(head["Session"])

            sess = Session(
                started_at=day,
                session_type=session_type,
                readiness=int(round(head["Readiness"])) if pd.notna(head["Readiness"]) else None,
                fatigue=int(round(head["Fatigue"])) if pd.notna(head["Fatigue"]) else None,
                sensitivity=int(round(head["Sensitivity"])) if pd.notna(head["Sensitivity"]) else None,
                quality=int(round(head["Quality"])) if pd.notna(head["Quality"]) else None,
                time_minutes=int(head["time_min"]) if pd.notna(head["time_min"]) else None,
                notes=f"Backfilled from {Path(xlsx_path).name}",
            )
            db.add(sess)
            db.flush()

            ex_powers = []
            for _, r in rows.iterrows():
                canonical = canonicalize(r["Item"], aliases)
                ex = ensure_exercise(db, canonical, by_name)

                # Spreadsheet stores aggregate "3 sets × 10 reps @ 40kg" — expand to 3 set rows
                # All identical since we have no per-set granularity historically.
                set_rows = []
                for i in range(int(r["Sets"])):
                    s = StrengthSet(
                        session_id=sess.id,
                        exercise_id=ex.id,
                        set_index=i + 1,
                        reps=int(r["Reps"]),
                        weight_kg=float(r["weight_kg"]),
                        rir=None,                             # not logged historically
                        local_sensitivity="none",
                        is_pr=False,                          # PR detector pass below
                        est_1rm=epley_e1rm(r["weight_kg"], int(r["Reps"])),
                    )
                    db.add(s)
                    set_rows.append({
                        "reps": int(r["Reps"]),
                        "weight_kg": float(r["weight_kg"]),
                        "rir": None,
                        "local_sensitivity": "none",
                    })
                db.flush()

                # Per-exercise Power Score using seed peak e1RM as anchor for early sessions
                seed_peak = by_name.get(canonical, {}).get("peak_e1rm_seed", 0.0)
                ep = exercise_power(
                    sets=set_rows,
                    ec=ex.ec_coefficient,
                    peak_e1rm=max(seed_peak, epley_e1rm(r["weight_kg"], int(r["Reps"]))),
                    readiness=sess.readiness or 8,
                )
                ex_powers.append(ep)

            # Session-level computation
            from app.services.power_score import TIME_BENCHMARKS_MIN
            bench = TIME_BENCHMARKS_MIN.get(session_type, 85.0)
            total = session_power(
                exercise_powers=ex_powers,
                quality=sess.quality or 8,
                fatigue=sess.fatigue or 8,
                sensitivity=sess.sensitivity or 8,
                time_minutes=sess.time_minutes or int(bench),
                benchmark_minutes=bench,
            )
            sess.total_power = total
            sess.index_vs_median = index_vs_median(total)

        db.commit()
        print("Backfill committed")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
