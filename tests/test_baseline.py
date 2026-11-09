import copy
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from sipp_baseline.generate import generate
from sipp_baseline.model import check_scenario, load, protocol, read_map
from sipp_baseline.runner import ROOT, benchmark, ensure_built, solve_batch
from sipp_baseline.validation import oracle, validate


def scenario(grid=None, forecasts=None, start=None, goal=None, horizon=180):
    grid = grid if grid is not None else ["."*13]
    return check_scenario({"schema_version": 1, "tick_seconds": .1, "horizon": horizon,
                           "grid": grid, "start": start or [0, 0, 0, 0],
                           "goal": goal or [len(grid)-1, len(grid[0])-1, 0],
                           "forecasts": forecasts or [{"id": "p0", "reservations": []}]})


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_built()

    def assert_oracle(self, data):
        results = solve_batch(data)
        for forecast, result in zip(data["forecasts"], results):
            self.assertEqual((result["status"], result["cost_ticks"]), oracle(data, forecast),
                             msg=json.dumps({"scenario": data, "forecast": forecast, "result": result}))
            validate(data, forecast, result)
        return results

    def test_forecast_replay_and_no_stale_state(self):
        data = load(ROOT / "examples/corridor.json")
        results = self.assert_oracle(data)
        self.assertEqual([r["cost_ticks"] for r in results], [100, 126, 100, None, 100])
        self.assertEqual(results[0]["steps"], results[-1]["steps"])
        self.assertEqual(results[0]["expansions"], results[-1]["expansions"])

    def test_split_merge_overlap_and_endpoint_changes(self):
        reservations = [[], [[0, 6, 30, 50]], [[0, 6, 30, 70]],
                        [[0, 6, 30, 40], [0, 6, 60, 70]],
                        [[0, 6, 30, 50], [0, 6, 40, 70], [0, 6, 30, 50]],
                        [[0, 4, 40, 40]], [[0, 4, 41, 41]], []]
        self.assert_oracle(scenario(forecasts=[{"id": str(i), "reservations": x}
                                             for i, x in enumerate(reservations)]))

    def test_stopped_goal_start_at_goal_and_horizon(self):
        result = self.assert_oracle(scenario(goal=[0, 0, 0], horizon=0))[0]
        self.assertEqual(result["cost_ticks"], 0)
        self.assertEqual(result["steps"], [])
        self.assertEqual(self.assert_oracle(scenario(horizon=99))[0]["status"], "no_path")
        self.assertEqual(self.assert_oracle(scenario(horizon=100))[0]["cost_ticks"], 100)

    def test_initial_velocity_no_waiting(self):
        data = scenario(start=[0, 0, 0, 1], goal=[0, 4, 0], horizon=50)
        self.assertEqual(self.assert_oracle(data)[0]["cost_ticks"], 40)
        data["forecasts"][0]["reservations"] = [[0, 2, 0, 20]]
        self.assertEqual(self.assert_oracle(data)[0]["status"], "no_path")

    def test_nonzero_start_time(self):
        data = scenario(horizon=200)
        data["start_tick"] = 13
        self.assertEqual(self.assert_oracle(data)[0]["cost_ticks"], 113)

    def test_blocked_start_and_static_barrier(self):
        data = scenario(forecasts=[{"id": "p0", "reservations": [[0, 0, 0, 1]]}])
        self.assertEqual(self.assert_oracle(data)[0]["status"], "invalid_start")
        self.assertEqual(self.assert_oracle(scenario(grid=["......#......"]))[0]["status"], "no_path")

    def test_turn_and_brake(self):
        result = self.assert_oracle(scenario(grid=["."*9]*9, horizon=200))[0]
        self.assertEqual(result["cost_ticks"], 180)
        self.assertTrue(any(s["action"] == "right" for s in result["steps"]))

    def test_expansion_limit_is_distinct_from_no_path(self):
        data = scenario()
        result = solve_batch(data, max_expansions=0)[0]
        self.assertEqual(result["status"], "expansion_limit")
        self.assertIsNone(result["cost_ticks"])

    def test_validator_rejects_corruption(self):
        data = scenario()
        result = solve_batch(data)[0]
        validate(data, data["forecasts"][0], result)
        bad = copy.deepcopy(result)
        bad["steps"][0]["end"] += 1
        with self.assertRaises(ValueError):
            validate(data, data["forecasts"][0], bad)
        blocked = {"id": "blocked", "reservations": [[0, 2, 0, 180]]}
        with self.assertRaises(ValueError):
            validate(data, blocked, result)
        bad = copy.deepcopy(result)
        bad["steps"].insert(1, {"action": "wait", "from": [0, 4, 0, 1], "to": [0, 4, 0, 1],
                                "start": 40, "end": 41})
        with self.assertRaises(ValueError):
            validate(data, data["forecasts"][0], bad)

    def test_randomized_differential(self):
        # 80 seeds x 3 snapshots: arbitrary reservations, gaps, overlaps, endpoints,
        # orientations and velocities. Oracle explicitly enumerates time states.
        for seed in range(80):
            rng = random.Random(seed)
            h, w = rng.choice([(1, 13), (9, 9), (5, 13)])
            grid = ["".join("#" if rng.random() < .025 else "." for _ in range(w)) for _ in range(h)]
            grid[0] = "."+grid[0][1:]
            grid[-1] = grid[-1][:-1]+"."
            forecasts = []
            for revision in range(3):
                rs = []
                for _ in range(18):
                    a = rng.randrange(130)
                    rs.append([rng.randrange(h), rng.randrange(w), a, min(180, a+rng.randrange(1, 45))])
                forecasts.append({"id": str(revision), "reservations": rs})
            with self.subTest(seed=seed):
                self.assert_oracle(scenario(grid=grid, forecasts=forecasts,
                                           start=[0, 0, rng.randrange(4), rng.randrange(2)],
                                           goal=[h-1, w-1, rng.randrange(2)]))

    def test_upstream_cost_agreement(self):
        # Compile the unmodified pinned source behind a test-only input adapter.
        binary = ROOT / "build/upstream_reference"
        subprocess.run(["g++", "-std=c++17", "-O2", str(ROOT / "tests/upstream_reference.cpp"),
                        "-o", str(binary)], check=True)
        for seed in range(8):
            data = generate(["."*13]*9, seed=seed, updates=2, obstacles=3, horizon=220)
            ours = solve_batch(data)
            payload = "".join(protocol(data, f, 1_000_000) for f in data["forecasts"])
            process = subprocess.run([str(binary)], input=payload, text=True, capture_output=True,
                                     check=True, timeout=30)
            reference = [json.loads(row) for row in process.stdout.splitlines()]
            self.assertEqual([(r["status"], r["cost_ticks"]) for r in ours],
                             [(r["status"], r["cost_ticks"]) for r in reference])


class InfrastructureTests(unittest.TestCase):
    def test_generator_determinism_and_zero_change(self):
        a = generate(["."*13]*9, seed=7, updates=3, probability=0)
        self.assertEqual(a, generate(["."*13]*9, seed=7, updates=3, probability=0))
        self.assertTrue(all(f["reservations"] == a["forecasts"][0]["reservations"] for f in a["forecasts"]))
        b = generate(["."*13]*9, seed=7, updates=3, probability=1)
        self.assertTrue(all(len(f["events"]) == 4 for f in b["forecasts"][1:]))

    def test_input_validation(self):
        for field, value in [("horizon", -1), ("grid", ["..", "."]), ("tick_seconds", 1),
                             ("start", [0, 0, 4, 0]), ("forecasts", [])]:
            data = scenario()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_scenario(data)

    def test_map_formats(self):
        self.assertEqual(len(read_map(ROOT / "maps/empty_64_64.txt")), 64)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.map"
            path.write_text("type octile\nheight 2\nwidth 3\nmap\n.@.\n...\n")
            self.assertEqual(read_map(path), [".#.", "..."])

    def test_measurement_artifacts(self):
        data = load(ROOT / "examples/corridor.json")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "experiment"
            summary = benchmark(data, output, repeats=2, warmups=1, check_oracle=True)
            manifest = json.loads((output / "manifest.json").read_text())
            rows = [json.loads(x) for x in (output / "results.jsonl").read_text().splitlines()]
            self.assertTrue(manifest["complete"])
            self.assertEqual(len(rows), 10)
            self.assertEqual(len(summary), 5)
            self.assertTrue((output / "summary.csv").exists())
            aggregate = json.loads((output / "aggregate.json").read_text())
            self.assertEqual(aggregate["updates"]["queries"], 4)
            self.assertEqual(aggregate["updates"]["solved_fraction"], .75)
            self.assertTrue(all(r["oracle_checked"] for r in rows))
            self.assertTrue(all(r["total_us"] >= r["search_us"] >= 0 for r in rows))
            with self.assertRaises(ValueError):
                benchmark(data, output)


if __name__ == "__main__":
    unittest.main()
