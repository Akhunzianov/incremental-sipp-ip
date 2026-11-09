import subprocess
import unittest

from sipp_baseline.model import load
from sipp_baseline.runner import ROOT, solve_batch
from sipp_baseline.validation import validate


class AdaptiveTests(unittest.TestCase):
    def test_repair_after_fallback_uses_the_retained_forecast(self):
        subprocess.run(['make', 'build-adaptive'], cwd=ROOT, check=True, capture_output=True)
        data = load(ROOT / 'examples/diverse-pulses/seed-7/agents-2/scenario.json')
        data['grid'] += ['.' * 13] * 3
        initial, pulse = data['forecasts']
        widespread = [[r, c, 40, 80] for r in range(2, 5) for c in range(13)]
        broad = dict(pulse, reservations=pulse['reservations'] + widespread)
        forecasts = [initial, broad, pulse, initial]
        adaptive = solve_batch(data, forecasts, binary=ROOT / 'build/sipp_ip_adaptive', binary_args=(32,10))
        baseline = solve_batch(data, forecasts)
        self.assertEqual([r['strategy'] for r in adaptive], ['repair', 'full_replan', 'repair', 'repair'])
        self.assertGreater(baseline[2]['cost_ticks'], baseline[0]['cost_ticks'])
        for forecast, result, reference in zip(forecasts, adaptive, baseline):
            self.assertEqual((result['status'], result['cost_ticks']),
                             (reference['status'], reference['cost_ticks']))
            validate(data, forecast, result)
