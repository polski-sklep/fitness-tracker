from app.services.claude_extractor import _parse_responses, _strip_json_fences


def test_strip_json_fences_with_json_tag():
    raw = '```json\n{"a": 1}\n```'
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_strip_json_fences_no_tag():
    raw = '```\n{"a": 1}\n```'
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_strip_json_fences_no_fences():
    raw = '{"a": 1}'
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_strip_json_fences_with_whitespace():
    raw = '   ```json\n{"a": 1}\n```   '
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_strip_json_fences_single_line():
    raw = '```json{"a": 1, "b": "hello"}```'
    assert _strip_json_fences(raw) == '{"a": 1, "b": "hello"}'


def test_strip_json_fences_with_prose_preamble():
    raw = "Here's the parsed data:\n\n```json\n{\"a\": 1}\n```"
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_strip_json_fences_nested_braces():
    raw = '```json{"a": {"nested": "value"}, "b": 2}```'
    assert _strip_json_fences(raw) == '{"a": {"nested": "value"}, "b": 2}'


def test_strip_json_fences_string_containing_brace():
    raw = '{"text": "this } is in a string", "valid": true}'
    expected = '{"text": "this } is in a string", "valid": true}'
    assert _strip_json_fences(raw) == expected


def test_strip_json_fences_escaped_quote_in_string():
    raw = '{"text": "she said \\"hi\\"", "value": 1}'
    expected = '{"text": "she said \\"hi\\"", "value": 1}'
    assert _strip_json_fences(raw) == expected


def test_parse_responses_with_session_array():
    raw = """
    [
      {"modality": "cycling", "session_type": "cycling", "cycling": {"distance_km": 10, "kcal": 200, "duration_min": 20, "avg_hr": null}},
      {"modality": "cycling", "session_type": "cycling", "cycling": {"distance_km": 12, "kcal": 240, "duration_min": 24, "avg_hr": null}}
    ]
    """
    sessions = _parse_responses(raw)
    assert len(sessions) == 2
    assert sessions[0].cycling.kcal == 200
