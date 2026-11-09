import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from sipp_baseline.paper import MAPS, VENDOR, import_samples, parse_instance, recorded_result, write_index
from sipp_baseline.runner import solve_batch
from sipp_baseline.validation import validate


class PaperSampleTests(unittest.TestCase):
    def test_loader_matches_upstream_time_scaling_and_coordinates(self):
        text = ('start_cell: x= 5 y= 6 orientation= 0\r\n'
                'goal_cell: x= 59 y= 58\r\n'
                'reserved_interval_at_cell: x= 7 y= 8 from_timestep: 3 to_timestep: 4000\r\n')
        start, goal, reservations = parse_instance(text)
        self.assertEqual(start, [5, 6, 0, 0])
        self.assertEqual(goal, [59, 58, 0])
        self.assertEqual(reservations, [[7, 8, 30, 40000]])
        with self.assertRaises(ValueError):
            parse_instance(text+'unrecognized row\n')

    def test_released_sample_inventory_and_source_digest(self):
        manifest = json.loads((VENDOR / 'tests/manifest.json').read_text())
        self.assertEqual(len(manifest), 35)
        for name in MAPS:
            self.assertEqual(sum(row['map'] == name for row in manifest), 7)
        entry = next(row for row in manifest if row['map'] == 'empty_64_64')
        raw = gzip.decompress((VENDOR / 'tests' / entry['file']).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])

    def test_original_instance_roundtrip_and_recorded_cost_agreement(self):
        data = import_samples('empty_64_64')
        self.assertEqual(data['start'], [5, 5, 0, 0])
        self.assertEqual(data['goal'], [59, 59, 0])
        self.assertEqual(data['horizon'], 40000)
        self.assertEqual([f['paper']['density_denominator'] for f in data['forecasts']], [25,20,15,10,5,4,3])
        f = data['forecasts'][0]
        result = solve_batch(data, forecasts=[f])[0]
        self.assertEqual(result['status'], 'solved')
        self.assertEqual(result['cost_ticks'], f['paper']['recorded_result']['cost_ticks'])
        validate(data, f, result)
        source = gzip.decompress((VENDOR / 'tests' / f['paper']['file']).read_bytes()).decode()
        self.assertEqual(data['forecasts'][0]['reservations'], parse_instance(source)[2])

    def test_scientific_notation_in_authors_timing(self):
        reference = recorded_result('random128', 979, 0)
        self.assertEqual(reference['cost_ticks'], 2886)
        self.assertEqual(reference['recorded_runtime_us'], 1010240)

    def test_index_labels_independent_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_index(output, MAPS, [{'map': MAPS[0], 'matches_recorded_result': True}])
            html = (output / 'index.html').read_text()
            self.assertIn('independent tests', html)
            self.assertIn('200 instances', html)
            self.assertIn('empty_64_64/viewer.html', html)
            self.assertTrue((output / 'verification.json').exists())
