import copy
import json
from pathlib import Path
import tempfile
import unittest

from sipp_baseline.runner import ROOT
from sipp_baseline.visualize import export_viewer, merge_reservations, viewer_data


class VisualizationTests(unittest.TestCase):
    def fixture(self, directory):
        scenario = json.loads((ROOT / "examples/corridor.json").read_text())
        scenario["forecasts"] = scenario["forecasts"][:1]
        scenario["forecasts"][0]["id"] = '</script><script>alert("test")</script>'
        # A zero-action solved query also exercises a valid path with no primitives.
        scenario["goal"] = [0, 0, 0]
        (directory / "scenario.json").write_text(json.dumps(scenario))
        result = {"forecast_id": scenario["forecasts"][0]["id"], "repetition": 0,
                  "status": "solved", "cost_ticks": 0, "steps": [],
                  "total_us": 10, "expansions": 0, "projections": 0, "peak_open": 1}
        another = {**result, "repetition": 1, "total_us": 30}
        (directory / "results.jsonl").write_text(json.dumps(result)+"\n"+json.dumps(another)+"\n")
        return scenario, result

    def test_interval_compression_preserves_occupancy(self):
        reservations = [[0, 1, 5, 10], [0, 1, 0, 3], [0, 1, 3, 4],
                        [0, 1, 15, 17], [0, 1, 15, 17], [1, 0, 1, 1]]
        merged = merge_reservations(reservations)
        self.assertEqual(merged, [[0, 1, [[0, 10], [15, 17]]], [1, 0, [[1, 1]]]])
        for r in range(2):
            for c in range(2):
                intervals = next((xs for rr, cc, xs in merged if (r, c) == (rr, cc)), [])
                for tick in range(20):
                    expected = any(rr == r and cc == c and a <= tick <= b for rr, cc, a, b in reservations)
                    self.assertEqual(expected, any(a <= tick <= b for a, b in intervals))

    def test_export_is_offline_readonly_and_html_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            scenario, _ = self.fixture(directory)
            before = {name: (directory / name).read_bytes() for name in ['scenario.json', 'results.jsonl']}
            output = export_viewer(directory)
            html = output.read_text()
            payload = html.split('<script id="replay-data" type="application/json">')[1].split('</script>')[0]
            decoded = json.loads(payload)
            self.assertEqual(decoded["forecasts"][0]["id"], scenario["forecasts"][0]["id"])
            self.assertEqual(decoded["forecasts"][0]["validation"], "Path validated")
            self.assertEqual(decoded["forecasts"][0]["median_total_us"], 20)
            self.assertNotIn('<script>alert(', html)
            self.assertNotIn('<script src=', html)
            self.assertNotIn('fetch(', html)
            self.assertNotIn('__SIPP_VIEWER_DATA__', html)
            for name, content in before.items():
                self.assertEqual((directory / name).read_bytes(), content)
            with self.assertRaises(ValueError):
                export_viewer(directory)
            export_viewer(directory, force=True)
            with self.assertRaises(ValueError):
                export_viewer(directory, directory / 'scenario.json', force=True)

    def test_explicit_repetition_and_missing_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.fixture(directory)
            self.assertEqual(viewer_data(directory, repetition=1)["forecasts"][0]["result"]["total_us"], 30)
            with self.assertRaisesRegex(ValueError, 'expected one result'):
                viewer_data(directory, repetition=2)

    def test_invalid_path_is_flagged_for_debugging(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _, result = self.fixture(directory)
            result = copy.deepcopy(result)
            result["cost_ticks"] = 10
            (directory / 'results.jsonl').write_text(json.dumps(result)+'\n')
            validation = viewer_data(directory)["forecasts"][0]["validation"]
            self.assertTrue(validation.startswith('Validation failed:'))
