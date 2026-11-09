import unittest

from sipp_baseline.moving_replay import replay
from sipp_baseline.model import load
from sipp_baseline.runner import ROOT
from sipp_baseline.thresholds import measure
import subprocess


class ThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(['make','build-adaptive'],cwd=ROOT,check=True,capture_output=True)
        cls.data=load(ROOT/'examples/diverse-pulses/seed-7/agents-2/scenario.json')

    def test_combinations_and_cache_restoration(self):
        initial,pulse=self.data['forecasts']
        data=dict(self.data,forecasts=[initial,pulse,dict(initial,id='restore',revision_tick=15)])
        result=measure(data,[(0,0),(32,0),(0,100)],1,True)
        self.assertEqual(result['policy']['0/0'],str(('repair','full_replan','repair')))
        self.assertEqual(result['policy']['32/0'],str(('repair','repair','repair')))
        self.assertEqual(result['policy']['0/100'],result['policy']['32/0'])

    def test_conflict_in_committed_primitive(self):
        initial,pulse=self.data['forecasts']
        blocked=dict(pulse,reservations=pulse['reservations']+[[0,2,22,25]])
        result=replay(dict(self.data,forecasts=[initial,blocked]),32,10)
        self.assertEqual(result['outcome'],'committed_motion_conflict')

    def test_revision_mid_motion_advances_to_boundary(self):
        initial,pulse=self.data['forecasts']
        harmless=dict(pulse,reservations=initial['reservations']+[[0,12,350,360]])
        result=replay(dict(self.data,forecasts=[initial,harmless]),32,10)
        self.assertEqual(result['outcome'],'arrived')
        next_query=result['queries'][1]
        self.assertEqual((next_query['tick'],next_query['start']),(40,[0,4,0,1]))
        self.assertTrue(next_query['reset'])
