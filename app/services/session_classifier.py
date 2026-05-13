def classify_session_type(exercise_names: list[str] | str | None) -> str:
    if exercise_names is None:
        return "other"
    names = [exercise_names] if isinstance(exercise_names, str) else exercise_names
    text = " ".join(names).lower()

    if any(word in text for word in ("cycling", "bike", "ride")):
        return "cycling"
    if any(word in text for word in ("squat", "deadlift", "rdl", "leg press", "lunge", "hamstring", "quad", "glute")):
        return "lower_core"
    if any(word in text for word in ("pull-up", "pull up", "row", "pulldown", "face pull", "curl", "pec deck reverse")):
        return "upper_pull"
    if any(word in text for word in ("bench", "press", "dip", "push-up", "push up", "fly", "tricep")):
        return "upper_push"
    return "other"

