"""
extract_charts.py — Strategy 1 chart extraction (JS config parsing, no browser).
Callable as a library; no /tmp file IO.
"""

from __future__ import annotations

import json
import re


def _extract_json_object(text: str, start_idx: int) -> str | None:
    """Extract a balanced JSON/JS object starting at start_idx."""
    depth = 0
    in_string = False
    escape_next = False
    start = None

    for i in range(start_idx, min(start_idx + 15000, len(text))):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : i + 1]
    return None


def _sanitize(obj_str: str) -> str:
    """Remove trailing commas to coerce JS object literals toward valid JSON."""
    return re.sub(r",\s*([}\]])", r"\1", obj_str)


def _try_parse_chartjs(script_text: str) -> list[dict]:
    results = []
    for m in re.finditer(r"new Chart\s*\([^,]+,\s*(\{)", script_text):
        raw = _extract_json_object(script_text, m.start(1))
        if raw:
            clean = _sanitize(raw)
            try:
                results.append({"library": "chartjs", "config": json.loads(clean)})
            except json.JSONDecodeError:
                results.append({"library": "chartjs", "raw": raw[:3000]})
    return results


def _try_parse_plotly(script_text: str) -> list[dict]:
    results = []
    for m in re.finditer(r"Plotly\.(newPlot|react)\s*\(", script_text):
        after = script_text[m.end():]
        am = re.search(r"\[", after[:500])
        if not am:
            continue
        depth = 0
        start = None
        for i, ch in enumerate(after):
            if ch == "[":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0 and start is not None:
                    raw = after[start : i + 1]
                    clean = _sanitize(raw)
                    try:
                        results.append({"library": "plotly", "traces": json.loads(clean)})
                    except json.JSONDecodeError:
                        results.append({"library": "plotly", "raw": raw[:3000]})
                    break
    return results


def _try_parse_highcharts(script_text: str) -> list[dict]:
    results = []
    for m in re.finditer(
        r"Highcharts\.(chart|stockChart|mapChart)\s*\([^,]+,\s*(\{)", script_text
    ):
        raw = _extract_json_object(script_text, m.start(2))
        if raw:
            clean = _sanitize(raw)
            try:
                results.append({"library": "highcharts", "config": json.loads(clean)})
            except json.JSONDecodeError:
                results.append({"library": "highcharts", "raw": raw[:3000]})
    return results


def extract_charts(script_text: str, detected_libs: list[str]) -> list[dict]:
    """
    Attempt Strategy 1 (inline JS config extraction) for all detected libraries.
    Returns a list of chart dicts. Empty list means Strategy 2 (canvas screenshot)
    is needed if canvas elements were also found.
    """
    results = []
    if "chartjs" in detected_libs:
        results.extend(_try_parse_chartjs(script_text))
    if "plotly" in detected_libs:
        results.extend(_try_parse_plotly(script_text))
    if "highcharts" in detected_libs:
        results.extend(_try_parse_highcharts(script_text))
    return results
