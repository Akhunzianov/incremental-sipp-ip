import hashlib
import json
import platform
from pathlib import Path
import subprocess
import time

from .model import protocol
from .events import POLICY, planning_events, reused_result
from .validation import oracle, validate

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "build" / "sipp_ip"


def build():
    BINARY.parent.mkdir(exist_ok=True)
    subprocess.run(["g++", "-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Wpedantic",
                    str(ROOT / "src/planner.cpp"), "-o", str(BINARY)], check=True)
    return BINARY


def ensure_built(binary=None):
    if binary is not None:
        path = Path(binary).resolve()
        if not path.is_file():
            raise ValueError(f"binary does not exist: {path}")
        return path
    if not BINARY.exists() or any((ROOT / path).stat().st_mtime > BINARY.stat().st_mtime
                                 for path in ('src/planner.cpp','src/model.hpp','src/fresh.hpp')):
        build()
    return BINARY


def solve_batch(data, forecasts=None, max_expansions=1_000_000, binary=None, timeout=120):
    binary = ensure_built(binary)
    forecasts = data["forecasts"] if forecasts is None else forecasts
    payload = "".join(protocol(data, f, max_expansions) for f in forecasts)
    process = subprocess.run([str(binary)], input=payload, text=True, capture_output=True,
                             timeout=timeout, check=True)
    results = [json.loads(line) for line in process.stdout.splitlines()]
    if len(results) != len(forecasts):
        raise RuntimeError(f"planner returned {len(results)} results for {len(forecasts)} forecasts")
    return results


def benchmark(data, output, repeats=3, warmups=1, check_oracle=False, max_expansions=1_000_000,
              binary=None, timeout=120):
    custom_binary = binary is not None
    binary = ensure_built(binary)
    output = Path(output)
    if output.exists():
        raise ValueError(f"output directory already exists: {output}; choose a new path")
    output.mkdir(parents=True)
    selected,decisions = planning_events(data)
    decision_by_id = {d['forecast_id']:d for d in decisions}
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    (output / "scenario.json").write_text(json.dumps(data, indent=2) + "\n")
    try:
        git_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                               text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        git_revision = None
    git_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT,
                                             text=True, stderr=subprocess.DEVNULL).strip()) if (ROOT / ".git").exists() else None
    manifest = {"algorithm": "sipp-ip-full-replan", "implementation": "interval-projection-port-v1",
                "upstream_commit": "77ca7491345c00b1cec7d0b88fe96cc561e0be25",
                "git_revision": git_revision, "git_dirty": git_dirty, "platform": platform.platform(),
                "python": platform.python_version(), "binary": str(binary),
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "source_sha256": hashlib.sha256((ROOT / "src/planner.cpp").read_bytes()).hexdigest(),
                "model_sha256": hashlib.sha256((ROOT / "src/model.hpp").read_bytes()).hexdigest(),
                "scenario_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
                "build_flags": None if custom_binary else "-std=c++17 -O3 -DNDEBUG -Wall -Wextra -Wpedantic",
                "custom_binary": custom_binary,
                "repeats": repeats, "warmups": warmups, "oracle": check_oracle,
                "max_expansions": max_expansions, "timeout_seconds_per_batch": timeout,
                "complete": False}
    manifest.update({'evaluation_policy':POLICY,'received_forecasts':len(decisions),
                     'planner_queries':len(selected),'skipped_forecasts':len(decisions)-len(selected)})
    (output/'events.json').write_text(json.dumps(decisions,indent=2)+'\n')
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    reference = {}
    if check_oracle:
        reference = {f["id"]: oracle(data, f) for f in data["forecasts"]}
    fingerprints = {}
    with (output / "results.jsonl").open("w") as stream:
        for repetition in range(-warmups, repeats):
            wall_start = time.perf_counter_ns()
            invoked_results = solve_batch(data, forecasts=selected, max_expansions=max_expansions, binary=binary, timeout=timeout)
            measured = {f['id']:r for f,r in zip(selected,invoked_results)}
            results = []
            for forecast in data['forecasts']:
                decision = decision_by_id[forecast['id']]
                result = measured[decision['source_forecast_id']]
                result = dict(result) if decision['planner_invoked'] else reused_result(result)
                result.update({key:decision[key] for key in ('planner_invoked','reason','source_forecast_id')})
                results.append(result)
            batch_wall_us = (time.perf_counter_ns()-wall_start)/1000
            for forecast, result in zip(data["forecasts"], results):
                validation_start = time.perf_counter_ns()
                result["path_valid"] = validate(data, forecast, result)
                if check_oracle:
                    actual = result["status"], result["cost_ticks"]
                    if actual != reference[forecast["id"]]:
                        raise RuntimeError(f"oracle mismatch for {forecast['id']}: {actual} != {reference[forecast['id']]}")
                fingerprint = (result["status"], result["cost_ticks"], result["expansions"],
                               result["projections"], json.dumps(result["steps"], sort_keys=True))
                if forecast["id"] in fingerprints and fingerprints[forecast["id"]] != fingerprint:
                    raise RuntimeError("nondeterministic planner result")
                fingerprints[forecast["id"]] = fingerprint
                if repetition < 0:
                    continue
                result.update({"forecast_id": forecast["id"], "repetition": repetition,
                               "cost_seconds": None if result["cost_ticks"] is None else result["cost_ticks"]*0.1,
                               "validation_us": (time.perf_counter_ns()-validation_start)/1000,
                               "batch_wall_us": batch_wall_us,
                               "oracle_checked": check_oracle})
                stream.write(json.dumps(result, sort_keys=True) + "\n")
                stream.flush()
    summary = summarize(output / "results.jsonl", output / "summary.csv")
    aggregate = ({"instances": aggregate_queries(summary)} if data.get("metadata", {}).get("independent_instances")
                 else {"initial": aggregate_queries(summary[:1]),
                       "updates": aggregate_queries([r for r in summary[1:] if r['planner_invoked']]),
                       "received_forecasts":len(decisions),"skipped_forecasts":len(decisions)-len(selected),
                       "evaluation_policy":POLICY})
    (output / "aggregate.json").write_text(json.dumps(aggregate, indent=2) + "\n")
    manifest["complete"] = True
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return summary


def aggregate_queries(rows):
    import statistics
    statuses = {status: sum(r["status"] == status for r in rows)
                for status in ("solved", "no_path", "invalid_start", "expansion_limit")}
    return {"queries": len(rows), "statuses": statuses,
            "solved_fraction": statuses["solved"]/len(rows) if rows else None,
            "median_of_query_median_total_us": statistics.median(r["median_total_us"] for r in rows) if rows else None,
            "mean_expansions": statistics.mean(r["expansions"] for r in rows) if rows else None}


def summarize(path, output=None):
    import csv
    import math
    import statistics
    groups = {}
    for line in Path(path).read_text().splitlines():
        row = json.loads(line)
        groups.setdefault(row["forecast_id"], []).append(row)
    summary = []
    for forecast_id, rows in groups.items():
        times = sorted(r["total_us"] for r in rows)
        invoked = rows[0].get('planner_invoked',True)
        summary.append({"forecast_id": forecast_id, "samples": len(rows) if invoked else 0,
                        "planner_invoked":invoked,"source_forecast_id":rows[0].get('source_forecast_id',forecast_id),
                        "status": rows[0]["status"], "cost_ticks": rows[0]["cost_ticks"],
                        "median_total_us": statistics.median(times),
                        "p95_total_us": times[math.ceil(.95*len(times))-1],
                        "median_search_us": statistics.median(r["search_us"] for r in rows),
                        "expansions": rows[0]["expansions"], "projections": rows[0]["projections"],
                        "peak_open": rows[0]["peak_open"]})
    if output and summary:
        with Path(output).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)
    return summary
