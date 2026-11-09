import json
from pathlib import Path
import random
import tempfile
import unittest

from sipp_baseline.generate import shortest_path
from sipp_baseline.obstacle_routes import StaticRoutes
from sipp_baseline.suite import build_suite, changed_cells


class ComparisonSuiteTests(unittest.TestCase):
    def test_fast_routing_preserves_reference_bfs_choices(self):
        rng = random.Random(23)
        for case in range(5):
            grid = [''.join('#' if rng.random()<.15 else '.' for _ in range(10)) for _ in range(9)]
            forbidden = {(0,0),(8,9)}
            free = [(r,c) for r,row in enumerate(grid) for c,value in enumerate(row) if value=='.' and (r,c) not in forbidden]
            with StaticRoutes(grid,forbidden) as router:
                for _ in range(8):
                    source,waypoint,goal = rng.sample(free,3)
                    first = shortest_path(grid,source,waypoint,forbidden)
                    second = shortest_path(grid,waypoint,goal,forbidden) if first else None
                    expected = [list(p) for p in first+second[1:]] if first and second else None
                    self.assertEqual(router.via(source,waypoint,goal),expected)

    def test_changed_cells_counts_timelines_not_interval_rows(self):
        self.assertEqual(changed_cells([[0,0,0,10]],[[0,0,0,20],[1,1,0,10]]),2)
        self.assertEqual(changed_cells([[0,0,0,10]],[[0,0,0,10]]),0)

    def test_matched_suite_artifacts_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'suite'
            settings = dict(maps=('empty_64_64',),q_values=(0,.5),density=.001,
                            updates=1,horizon=1000,repeats=1,warmups=0)
            index = build_suite(output,**settings)
            suite = json.loads((output/'suite.json').read_text())
            self.assertTrue(suite['complete'])
            self.assertEqual(len(suite['runs']),2)
            self.assertEqual(suite['runs'][0]['initial_sha256'],suite['runs'][1]['initial_sha256'])
            self.assertTrue(index.exists())
            self.assertTrue((output/'comparison.csv').exists())
            self.assertIn('Left forecast replay',index.read_text())
            self.assertTrue(all((output/f['view']).exists() for run in suite['runs'] for f in run['forecasts']))
            result_path = output/'empty_64_64/q-0/results.jsonl'
            before = result_path.read_bytes()
            with self.assertRaises(ValueError):
                build_suite(output,**settings)
            build_suite(output,**settings,resume=True)
            self.assertEqual(result_path.read_bytes(),before)
            with self.assertRaises(ValueError):
                build_suite(output,**{**settings,'seed':8},resume=True)

    def test_invalid_q_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            for values in ((),(0,0),(-.1,), (float('nan'),)):
                with self.assertRaises(ValueError):
                    build_suite(Path(tmp)/'new',q_values=values)
