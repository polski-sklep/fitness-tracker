import json
from functools import lru_cache
from pathlib import Path

from app.services.power_score import EC_LOOKUP

SEED_FILE = Path(__file__).resolve().parents[2] / "seed_exercises.json"


@lru_cache
def load_seed_data() -> dict:
    with open(SEED_FILE) as seed_file:
        return json.load(seed_file)


@lru_cache
def load_seed() -> tuple[dict[str, str], dict[str, dict]]:
    seed = load_seed_data()
    aliases = {key.lower(): value.lower() for key, value in seed.get("aliases", {}).items()}
    by_name = {exercise["name"].lower(): exercise for exercise in seed.get("exercises", [])}
    return aliases, by_name


@lru_cache
def load_seed_peak_weights() -> dict[str, float]:
    seed = load_seed_data()
    return {name.lower(): float(weight) for name, weight in seed.get("seed_peak_weights", {}).items()}


@lru_cache
def load_seed_peak_e1rm() -> dict[str, float]:
    _, seed_by_name = load_seed()
    return {name: float(exercise.get("peak_e1rm_seed") or 0) for name, exercise in seed_by_name.items()}


def canonicalize(raw_name: str) -> str:
    aliases, _ = load_seed()
    key = (raw_name or "").strip().lower()
    return aliases.get(key, key)


def display_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split())


def ec_for_class(exercise_class: str | None) -> float:
    return EC_LOOKUP.get(exercise_class or "machine_compound", 0.85)
