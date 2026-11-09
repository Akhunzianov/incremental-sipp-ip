"""Import the pinned authors' released benchmark samples and build a viewer bundle."""
import gzip
import hashlib
import html
import json
from pathlib import Path
import re

from .model import check_scenario, read_map
from .runner import ROOT, benchmark
from .visualize import export_viewer

COMMIT = "77ca7491345c00b1cec7d0b88fe96cc561e0be25"
MAPS = ("empty_64_64", "room-64-64-16", "warehouse-10-20-10-2-2", "random128", "Sydney_2_256")
VENDOR = ROOT / "vendor/sipp-ip"
FACTORS = (25, 20, 15, 10, 5, 4, 3)


def parse_instance(text):
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("paper instance lacks start/goal")
    start = re.fullmatch(r"start_cell:\s+x=\s+(\d+)\s+y=\s+(\d+)\s+orientation=\s+(\d+)\s*", lines[0])
    goal = re.fullmatch(r"goal_cell:\s+x=\s+(\d+)\s+y=\s+(\d+)\s*", lines[1])
    if start is None or goal is None:
        raise ValueError("invalid paper instance start/goal header")
    reservations = []
    pattern = r"reserved_interval_at_cell:\s+x=\s+(\d+)\s+y=\s+(\d+)\s+from_timestep:\s+(\d+)\s+to_timestep:\s+(\d+)\s*"
    for number, line in enumerate(lines[2:], 3):
        match = re.fullmatch(pattern, line)
        if match is None:
            raise ValueError(f"invalid reservation at source line {number}")
        r, c, first, last = map(int, match.groups())
        # Match the authors' readInputs(): t1 *= F; t2 *= F; F = 10.
        reservations.append([r, c, first*10, last*10])
    return [*map(int, start.groups()), 0], [*map(int, goal.groups()), 0], reservations


def recorded_result(map_name, obstacles, test_index):
    path = VENDOR / "results" / f"res-{map_name}-SIPP-IP-obs{obstacles}.txt"
    lines = path.read_text().splitlines()
    if test_index >= len(lines):
        return None
    match = re.fullmatch(r"Success:([01]), Cost:([+-]?\d+), Runtime:([\d.eE+-]+)\s*", lines[test_index])
    if match is None:
        raise ValueError(f"invalid recorded result: {path.name}")
    solved, cost, runtime = match.groups()
    return {"status": "solved" if solved == "1" else "no_path",
            "cost_ticks": int(cost) if solved == "1" else None,
            "recorded_runtime_us": float(runtime)}


def import_samples(map_name):
    if map_name not in MAPS:
        raise ValueError(f"unsupported paper map: {map_name}")
    grid = read_map(ROOT / "maps" / f"{map_name}.txt")
    free = sum(row.count('.') for row in grid)
    manifest = json.loads((VENDOR / "tests/manifest.json").read_text())
    entries = [entry for entry in manifest if entry["map"] == map_name]
    entries.sort(key=lambda e: int(re.search(r"-(\d+)\.txt\.gz$", e["file"]).group(1)))
    forecasts, query = [], None
    for entry in entries:
        raw = gzip.decompress((VENDOR / "tests" / entry["file"]).read_bytes())
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"source digest mismatch: {entry['file']}")
        start, goal, reservations = parse_instance(raw.decode())
        if query is not None and query != (start, goal):
            raise ValueError("released queries differ; cannot group as one scenario")
        query = start, goal
        index, obstacles = map(int, re.search(r"-test-(\d+)-(\d+)\.txt\.gz$", entry["file"]).groups())
        factor = next((d for d in FACTORS if free//d == obstacles), None)
        if factor is None:
            raise ValueError("obstacle count does not match a released density")
        forecasts.append({"id": f"{obstacles} obstacles (1/{factor})", "reservations": reservations,
                          "paper": {**entry, "obstacles": obstacles, "density_denominator": factor,
                                    "test_index": index,
                                    "recorded_result": recorded_result(map_name, obstacles, index)}})
    if query is None:
        raise ValueError(f"no released samples for {map_name}")
    return check_scenario({"schema_version": 1, "tick_seconds": .1, "horizon": 40000,
                           "grid": grid, "start": query[0], "goal": query[1], "start_tick": 0,
                           "metadata": {"dataset_kind": "paper_samples", "map_name": map_name,
                                        "upstream_commit": COMMIT, "upstream_url": "https://github.com/PathPlanning/SIPP-IP",
                                        "independent_instances": True,
                                        "description": "Released test-0 samples; not the complete 200 instances per map/density."},
                           "forecasts": forecasts})


def build_paper_viewers(output, maps=MAPS, max_expansions=2_000_000, timeout=120, resume=False):
    output = Path(output)
    if output.exists() and not resume:
        raise ValueError(f"output already exists: {output}; choose a new directory")
    output.mkdir(parents=True, exist_ok=resume)
    reports = []
    for map_name in maps:
        print(f"Importing and planning {map_name}...", flush=True)
        scenario = import_samples(map_name)
        directory = output / map_name
        if directory.exists():
            manifest = json.loads((directory / "manifest.json").read_text())
            if (not resume or not manifest.get("complete") or manifest["max_expansions"] != max_expansions
                    or json.loads((directory / "scenario.json").read_text()) != scenario):
                raise ValueError(f"cannot reuse incomplete or different run: {directory}")
        else:
            benchmark(scenario, directory, repeats=1, warmups=0, max_expansions=max_expansions, timeout=timeout)
        export_viewer(directory, force=resume)
        rows = [json.loads(line) for line in (directory / "results.jsonl").read_text().splitlines()]
        for forecast, result in zip(scenario["forecasts"], rows):
            reference = forecast["paper"]["recorded_result"]
            matches = reference is not None and (result["status"], result["cost_ticks"]) == (reference["status"], reference["cost_ticks"])
            reports.append({"map": map_name, "instance": forecast["id"], "status": result["status"],
                            "cost_ticks": result["cost_ticks"], "source_cost_ticks": reference["cost_ticks"] if reference else None,
                            "matches_recorded_result": matches})
        write_index(output, maps, reports)
        print(f"Saved {directory / 'viewer.html'}", flush=True)
    return (output / "index.html").resolve()


def write_index(output, maps, reports):
    (output / "verification.json").write_text(json.dumps(reports, indent=2)+'\n')
    links = []
    for name in maps:
        rows = [r for r in reports if r["map"] == name]
        if not rows:
            continue
        matched = sum(r["matches_recorded_result"] for r in rows)
        links.append(f'<li><a href="{name}/viewer.html">{html.escape(name)}</a>'
                     f'<span>{len(rows)} released samples · {matched}/{len(rows)} results match the authors’ saved results</span></li>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SIPP-IP · Released benchmark samples</title><style>
body{font:16px/1.65 system-ui,sans-serif;background:#f3f5f5;color:#172c37;margin:0}main{max-width:900px;margin:55px auto;padding:0 24px}h1{font-size:36px;letter-spacing:-1px;line-height:1.2}a{color:#225ed5}small,p{color:#526a75}ul{list-style:none;padding:0;margin:30px 0}li{padding:18px 0;border-top:1px solid #d8e1e4}li a{font-size:21px;font-weight:600;text-decoration:none}li span{display:block;font-size:14px;color:#526a75;margin-top:3px}.label{font-size:12px;letter-spacing:2px;color:#087f76}
</style><main><div class="label">SIPP-IP / AUTHORS’ DATA</div><h1>Explore the released benchmark tests</h1>
<p>Original maps, queries and obstacle reservation intervals from the authors’ pinned repository. Select a map, then choose an obstacle density and play or scrub through time.</p>
<p>The release contains one sample at each of seven densities per map (35 total). The paper evaluated 200 instances per map and density. These are independent tests, not forecast updates.</p><ul>'''+''.join(links)+'''</ul>
<p>Robot trajectories and timings are new runs of our adapted baseline. The viewer reports whether feasibility and arrival cost match the authors’ saved results. Occupancy is exact to the released reservation data; individual obstacle identities are not available.</p>
<p><a href="https://arxiv.org/abs/2302.00776">Paper</a> · <a href="https://github.com/PathPlanning/SIPP-IP/tree/'''+COMMIT+'''/tests">Pinned released instances</a> · <a href="verification.json">Verification report</a></p></main></html>'''
    (output / "index.html").write_text(page)
