import json
import subprocess
import unittest

from sipp_baseline.model import protocol
from sipp_baseline.runner import ROOT
from sipp_baseline.validation import oracle, validate


class SuffixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(['make','build-adaptive'], cwd=ROOT, check=True, capture_output=True)

    def test_split_wait_shortcut_and_goal_endpoint(self):
        data = dict(grid=['.'*13], start=[0,0,0,0], goal=[0,12,0], horizon=200)
        old = [[0,5,40,80]]
        cases = [
            # Extra blockage after arrival permits a certificate during a wait.
            (old+[[0,12,180,190]], 'certified_suffix'),
            # The previous suffix remains feasible, but removing the blocker permits earlier arrival.
            ([], 'repair'),
            # The certificate's monotonicity window excludes U. Feasibility includes U.
            (old+[[0,12,141,141]], 'repair'),
        ]
        for reservations, strategy in cases:
            with self.subTest(strategy=strategy,reservations=reservations):
                query = dict(data,start_tick=10)
                forecast = dict(reservations=reservations)
                payload = protocol(data,dict(reservations=old),100000)+protocol(query,forecast,100000)
                run = subprocess.run([ROOT/'build/sipp_ip_adaptive'],input=payload,text=True,
                                     capture_output=True,check=True)
                previous,result = map(json.loads,run.stdout.splitlines())
                self.assertEqual(previous['cost_ticks'],141)
                self.assertEqual(result['strategy'],strategy)
                self.assertEqual((result['status'],result['cost_ticks']),oracle(query,forecast))
                validate(query,forecast,result)
                if strategy=='certified_suffix':
                    self.assertEqual(result['steps'][0]['start'],10)
                    self.assertEqual(result['expansions'],0)
