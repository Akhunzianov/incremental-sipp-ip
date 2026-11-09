"""Export a self-contained offline viewer for a saved benchmark run."""
import json
import base64
import gzip
from pathlib import Path
import statistics

from .model import load
from .validation import validate


def merge_reservations(reservations):
    cells = {}
    for r, c, lo, hi in reservations:
        cells.setdefault((r, c), []).append((lo, hi))
    output = []
    for (r, c), intervals in sorted(cells.items()):
        merged = []
        for lo, hi in sorted(intervals):
            if merged and lo <= merged[-1][1]+1:
                merged[-1][1] = max(hi, merged[-1][1])
            else:
                merged.append([lo, hi])
        output.append([r, c, merged])
    return output


def viewer_data(directory, repetition=0):
    directory = Path(directory)
    scenario = load(directory / "scenario.json")
    groups = {}
    for line in (directory / "results.jsonl").read_text().splitlines():
        row = json.loads(line)
        groups.setdefault(row["forecast_id"], []).append(row)
    forecasts = []
    for forecast in scenario["forecasts"]:
        rows = groups.get(forecast["id"], [])
        selected = [r for r in rows if r["repetition"] == repetition]
        if len(selected) != 1:
            raise ValueError(f"expected one result for {forecast['id']}, repetition {repetition}")
        result = selected[0]
        try:
            verified = validate(scenario, forecast, result)
            validation = "Path validated" if verified else "No trajectory to validate"
        except (ValueError, KeyError, TypeError) as error:
            validation = f"Validation failed: {error}"
        forecasts.append({"id": forecast["id"], "events": forecast.get("events", []),
                          "paper": forecast.get("paper"),
                          "cells": merge_reservations(forecast["reservations"]),
                          "result": result, "validation": validation,
                          "median_total_us": statistics.median(r["total_us"] for r in rows),
                          "samples": len(rows)})
    return {"name": directory.name, "grid": scenario["grid"], "start": scenario["start"],
            "goal": scenario["goal"], "start_tick": scenario.get("start_tick", 0),
            "horizon": scenario["horizon"], "tick_seconds": scenario["tick_seconds"],
            "metadata": scenario.get("metadata", {}), "repetition": repetition,
            "forecasts": forecasts}


def export_viewer(directory, output=None, repetition=0, force=False):
    directory = Path(directory)
    output = Path(output) if output else directory / "viewer.html"
    if output.exists() and not force:
        raise ValueError(f"output already exists: {output}; use --force to replace it")
    # Protect original run data, even if --force was supplied.
    if output.suffix.lower() != ".html":
        raise ValueError("viewer output must have the .html extension")
    payload = json.dumps(viewer_data(directory, repetition), separators=(",", ":"), ensure_ascii=True)
    if len(payload) > 2_000_000:
        payload = json.dumps({"encoding": "gzip-base64", "payload": base64.b64encode(
            gzip.compress(payload.encode(), mtime=0)).decode()})
    # JSON is embedded as data, never evaluated; escape HTML script delimiters.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    template = Path(__file__).with_name("viewer.html").read_text()
    html = template.replace("__SIPP_VIEWER_DATA__", payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    return output.resolve()
