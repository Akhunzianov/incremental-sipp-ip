import copy
import json
import random
import subprocess
import unittest

from sipp_baseline.generate import canonical, change_obstacle, generate, obstacle_reservations
from sipp_baseline.model import read_map
from sipp_baseline.runner import ROOT
from sipp_baseline.upstream_generator import build_generator, generate_base


class UpstreamGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_generator()

    def test_zero_change_matches_unmodified_generator_both_branches(self):
        binary = ROOT / 'build/upstream_generator_reference'
        subprocess.run(['g++','-std=c++17','-O2','-Wno-return-type',
                        str(ROOT/'tests/upstream_generator_reference.cpp'),'-o',str(binary)],check=True)
        grid = ['.'*13]*9
        for policy in ('custom','empty_64_64'):
            for seed in (1,7,42):
                with self.subTest(policy=policy,seed=seed):
                    s = generate(grid,seed=seed,updates=2,obstacles=4,change_probability=0,
                                 start=[0,0,0,0],goal=[8,12,0],map_name=policy)
                    payload = f'9 13 {policy} {seed} 4 0 0 8 12\n'+'\n'.join(grid)+'\n'
                    ref = subprocess.run([str(binary)],input=payload,text=True,capture_output=True,check=True,timeout=30)
                    expected = json.loads(ref.stdout)
                    for forecast in s['forecasts']:
                        self.assertEqual(forecast['reservations'],expected)
                        self.assertFalse(forecast['events'])

    def test_initial_forecast_shared_across_q_and_density_prefix(self):
        grid = ['.'*13]*9
        zero = generate(grid,seed=42,updates=2,obstacles=4,change_probability=0)
        changed = generate(grid,seed=42,updates=2,obstacles=4,change_probability=1)
        self.assertEqual(zero['forecasts'][0],changed['forecasts'][0])
        larger = generate(grid,seed=42,updates=0,obstacles=6)
        self.assertEqual(zero['forecasts'][0]['obstacles'],larger['forecasts'][0]['obstacles'][:4])

    def test_paper_query_density_and_source_clipping(self):
        grid = read_map(ROOT/'maps/empty_64_64.txt')
        full = generate(grid,map_name='empty_64_64',seed=7,updates=0,density=.04,change_probability=0)
        self.assertEqual(full['start'],[5,5,0,0])
        self.assertEqual(full['goal'],[59,59,0])
        self.assertEqual(full['metadata']['obstacles'],163)
        self.assertEqual(full['metadata']['change_probability_symbol'],'q')
        clipped = generate(grid,map_name='empty_64_64',seed=7,updates=0,density=.04,horizon=1000)
        self.assertEqual(clipped['forecasts'][0]['reservations'],canonical(full['forecasts'][0]['reservations'],1000))

    def test_causal_prefix_and_legal_obstacle_motion(self):
        s = generate(['.'*24]*24,seed=42,updates=10,obstacles=12,change_probability=1)
        applied = 0
        for previous,current in zip(s['forecasts'],s['forecasts'][1:]):
            self.assertEqual(canonical(previous['reservations'],current['revision_tick']),
                             canonical(current['reservations'],current['revision_tick']))
            for event in current['events']:
                self.assertGreater(event['effective_tick'],current['revision_tick'])
                applied += event['outcome']=='applied'
            for before,after in zip(previous['obstacles'],current['obstacles']):
                self.assertEqual(before['goal'],after['goal'])
                self.assertEqual(before['nodes'][0],after['nodes'][0])
                for a,b in zip(after['nodes'],after['nodes'][1:]):
                    self.assertGreater(b[2],a[2])
                    self.assertLessEqual(max(abs(a[0]-b[0]),abs(a[1]-b[1])),1)
                    self.assertEqual(s['grid'][b[0]][b[1]],'.')
                    self.assertNotIn(b[:2],[s['start'][:2],s['goal'][:2]])
        self.assertGreater(applied,0)

    def test_each_change_mode_preserves_inflight_edge_and_goal(self):
        obstacle = {'id':0,'base_step_ticks':20,'nodes':[[1,1,0],[1,2,20],[1,3,40],[1,4,60]],
                    'goal':[1,4],'extra_reservations':[]}
        grid = ['.'*9]*9
        forbidden = {(0,0),(8,8)}
        free = [(r,c) for r in range(9) for c in range(9) if (r,c) not in forbidden]
        for mode in ('waypoint','pause','accelerate','decelerate'):
            with self.subTest(mode=mode):
                updated,event = change_obstacle(copy.deepcopy(obstacle),5,mode,random.Random(42),grid,free,forbidden,40000)
                self.assertIsNotNone(updated)
                self.assertEqual(event['outcome'],'applied')
                self.assertEqual(updated['nodes'][:2],obstacle['nodes'][:2])
                self.assertEqual(updated['goal'],obstacle['goal'])
                self.assertEqual(canonical(obstacle_reservations(obstacle,40000),5),
                                 canonical(obstacle_reservations(updated,40000),5))
                if mode=='waypoint':
                    self.assertIn(event['waypoint'],[n[:2] for n in updated['nodes']])
                if mode=='pause':
                    self.assertEqual(updated['nodes'][1][:2],updated['nodes'][2][:2])
                if mode=='accelerate':
                    self.assertLess(updated['nodes'][-1][2],obstacle['nodes'][-1][2])
                if mode=='decelerate':
                    self.assertGreater(updated['nodes'][-1][2],obstacle['nodes'][-1][2])

    def test_invalid_parameters_and_zero_obstacles(self):
        for kwargs in ({'change_probability':-1},{'change_probability':float('nan')},
                       {'density':.1,'obstacles':3},{'update_interval':0},{'updates':3,'horizon':200}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                generate(['.'*13]*9,**kwargs)
        s = generate(['.'*13]*9,obstacles=0,change_probability=1)
        self.assertTrue(all(not f['reservations'] for f in s['forecasts']))
