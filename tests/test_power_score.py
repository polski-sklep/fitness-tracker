from app.services.power_score import epley_e1rm, exercise_power, index_vs_median, session_power


def test_epley_e1rm() -> None:
    assert epley_e1rm(100, 6) == 120


def test_median_like_session_indexes_near_100() -> None:
    sets = [{"reps": 10, "weight_kg": 100, "rir": 1, "local_sensitivity": "none"} for _ in range(3)]
    score = exercise_power(sets, ec=1.0, peak_e1rm=133.3333333333, readiness=8)
    total = session_power([score], quality=8, fatigue=8, sensitivity=9, time_minutes=95, benchmark_minutes=94.5)
    assert 95 <= index_vs_median(total, median=total) <= 105


def test_low_readiness_increases_adjusted_power() -> None:
    sets = [{"reps": 5, "weight_kg": 140, "rir": 1, "local_sensitivity": "none"} for _ in range(3)]
    normal = exercise_power(sets, ec=1.0, peak_e1rm=170, readiness=8)
    low_readiness = exercise_power(sets, ec=1.0, peak_e1rm=170, readiness=4)
    assert low_readiness > normal


def test_local_sensitivity_penalizes_exercise_power() -> None:
    clean_sets = [{"reps": 8, "weight_kg": 80, "rir": 2, "local_sensitivity": "none"} for _ in range(3)]
    mild_sets = [{"reps": 8, "weight_kg": 80, "rir": 2, "local_sensitivity": "mild"} for _ in range(3)]
    clean = exercise_power(clean_sets, ec=0.85, peak_e1rm=110, readiness=8)
    mild = exercise_power(mild_sets, ec=0.85, peak_e1rm=110, readiness=8)
    assert mild < clean
    assert mild == clean * 0.85

