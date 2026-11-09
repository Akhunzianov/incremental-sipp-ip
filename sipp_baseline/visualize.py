"""Export a self-contained offline viewer for a saved benchmark run."""
import json
import base64
import gzip
import html
from pathlib import Path
import statistics

from .model import load
from .validation import validate

MAX_VIEWER_BYTES = 8_000_000


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
                          "revision_tick": forecast.get("revision_tick"),
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


def render_viewer(data):
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    if len(payload) > 2_000_000:
        payload = json.dumps({"encoding": "gzip-base64", "payload": base64.b64encode(
            gzip.compress(payload.encode(), mtime=0)).decode()})
    # JSON is embedded as data, never evaluated; escape HTML script delimiters.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    template = Path(__file__).with_name("viewer.html").read_text()
    return template.replace("__SIPP_VIEWER_DATA__", payload)


def export_viewer(directory, output=None, repetition=0, force=False):
    directory = Path(directory)
    output = Path(output) if output else directory / "viewer.html"
    if output.exists() and not force:
        raise ValueError(f"output already exists: {output}; use --force to replace it")
    # Protect original run data, even if --force was supplied.
    if output.suffix.lower() != ".html":
        raise ValueError("viewer output must have the .html extension")
    data = viewer_data(directory, repetition)
    document = render_viewer(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    if len(document.encode()) > MAX_VIEWER_BYTES and len(data["forecasts"]) > 1:
        children = [output.with_name(f"{output.stem}-instance-{i+1:02}.html") for i in range(len(data["forecasts"]))]
        if not force and any(path.exists() for path in children):
            raise ValueError("an instance viewer already exists; use --force to replace it")
        rows = []
        for forecast, child in zip(data["forecasts"], children):
            subset = {**data, "forecasts": [forecast],
                      "metadata": {**data.get("metadata", {}), "viewer_index": output.name}}
            child.write_text(render_viewer(subset))
            result = forecast["result"]
            cost = '—' if result['cost_ticks'] is None else f"{result['cost_ticks']*.1:.1f} s"
            rows.append(f'<tr><td><a href="{html.escape(child.name, quote=True)}">{html.escape(forecast["id"])}</a></td>'
                        f'<td>{html.escape(result["status"])}</td><td>{cost}</td>'
                        f'<td>{forecast["median_total_us"]/1000:.3f}</td><td>{result["expansions"]:,}</td></tr>')
        name = html.escape(str(data.get('metadata', {}).get('map_name', data['name'])))
        paper = data.get('metadata', {}).get('dataset_kind') == 'paper_samples'
        back = '<a href="../index.html">← Choose another map</a>' if paper else ''
        note = ('These are independent released samples. Timings come from our adapted planner; they are not the paper’s reported runtimes.'
                if paper else 'These are saved forecast snapshots. Exporting this viewer does not rerun the planner or change measurements.')
        document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{name} · Test viewers</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;background:#f3f5f5;color:#172c37;margin:0}}main{{max-width:1000px;margin:45px auto;padding:0 24px}}h1{{font-size:32px;letter-spacing:-1px}}a{{color:#225ed5}}p{{color:#526a75}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{padding:14px;text-align:left;border-bottom:1px solid #d8e1e4}}th{{font-size:13px}}.scroll{{overflow:auto}}</style></head><body><main>
{back}<h1>{name}</h1><p>Choose a test to open its animated viewer. Each file includes its own reservation data and robot trajectory, so it works offline. This large replay is split into smaller files for reliable previewing.</p>
<div class="scroll"><table><thead><tr><th>Test</th><th>Status</th><th>Arrival</th><th>Replan (ms)</th><th>Expansions</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>{note}</p></main></body></html>'''
    output.write_text(document)
    return output.resolve()
