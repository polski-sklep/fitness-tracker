EC_LOOKUP = {
    "heavy_compound": 1.00,
    "bw_compound": 0.95,
    "db_compound": 0.92,
    "machine_compound": 0.85,
    "isolation": 0.70,
    "corrective": 0.55,
}

RIR_EFFORT = {0: 0.95, 1: 1.00, 2: 0.93, 3: 0.82, 4: 0.70}

LS_PENALTY = {"none": 1.00, "mild": 0.85, "moderate": 0.65, "severe": 0.40}

TIME_BENCHMARKS_MIN = {
    "lower_core": 94.5,
    "upper_pull": 77.0,
    "upper_push": 81.0,
    "cycling": None,
    "other": 85.0,
}

SESSION_MEDIAN_POWER = 3112


def epley_e1rm(weight_kg: float, reps: int) -> float:
    return weight_kg * (1 + reps / 30)


def exercise_power(
    sets: list[dict],
    ec: float,
    peak_weight_kg: float,
    readiness: float | None,
    peak_e1rm: float | None = None,
) -> float:
    """Compute per-exercise Power Score using Power Formula v1.1.

    v1.1 uses working weight relative to lifetime peak working weight instead
    of Epley-estimated 1RM for relative intensity. ``peak_e1rm`` is retained
    for backwards compatibility and is not used by the v1.1 calculation.
    """
    if not sets:
        return 0.0

    readiness = float(readiness) if readiness is not None else None
    peak_weight_kg = float(peak_weight_kg) if peak_weight_kg is not None else 0.0
    ec = float(ec)
    for set_payload in sets:
        if set_payload.get("weight_kg") is not None:
            set_payload["weight_kg"] = float(set_payload["weight_kg"])
        if set_payload.get("reps") is not None:
            set_payload["reps"] = int(set_payload["reps"])
        if set_payload.get("rir") is not None:
            set_payload["rir"] = int(set_payload["rir"])

    set_count = len(sets)
    avg_weight = sum(float(s.get("weight_kg") or 0) for s in sets) / set_count
    avg_reps = sum(int(s["reps"]) for s in sets) / set_count
    volume = set_count * avg_reps * avg_weight
    relative_intensity = avg_weight / peak_weight_kg if peak_weight_kg > 0 else 1.0
    relative_intensity = min(relative_intensity, 1.20)

    rir_values = [s.get("rir") for s in sets if s.get("rir") is not None]
    if rir_values:
        effort = sum(RIR_EFFORT.get(min(int(r), 4), 0.70) for r in rir_values) / len(rir_values)
    else:
        effort = 1.00

    local_sensitivity = min(LS_PENALTY[s.get("local_sensitivity", "none")] for s in sets)
    readiness_term = (readiness / 10) ** 0.4 if readiness else 1.0

    return (volume * ec * relative_intensity * effort * local_sensitivity) / readiness_term


def session_power(
    exercise_powers: list[float],
    quality: float | None,
    fatigue: float | None,
    sensitivity: float | None,
    time_minutes: int | None,
    benchmark_minutes: float | None,
) -> float:
    quality = float(quality) if quality is not None else 8.0
    fatigue = float(fatigue) if fatigue is not None else 8.0
    sensitivity = float(sensitivity) if sensitivity is not None else 8.0
    benchmark_minutes = float(benchmark_minutes) if benchmark_minutes is not None else 85.0
    time_minutes = int(time_minutes) if time_minutes is not None else int(benchmark_minutes)

    base = sum(exercise_powers)
    quality_term = (quality / 10) ** 1.2
    fatigue_term = max(0.10, 1 - 0.04 * (fatigue - 7.75) ** 2)

    if sensitivity >= 9:
        sensitivity_term = 1.00
    elif sensitivity >= 7:
        sensitivity_term = 1 - 0.04 * (9 - sensitivity)
    elif sensitivity >= 5:
        sensitivity_term = 0.92 - 0.08 * (7 - sensitivity)
    else:
        sensitivity_term = max(0.10, 0.76 - 0.15 * (5 - sensitivity))

    time_term = (benchmark_minutes / time_minutes) ** 0.4 if time_minutes else 1.0
    return base * quality_term * fatigue_term * sensitivity_term * time_term


def index_vs_median(total: float, median: float = SESSION_MEDIAN_POWER) -> float:
    return (total / median) * 100
