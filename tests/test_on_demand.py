import json
import subprocess
import unittest

from sipp_baseline.model import protocol
from sipp_baseline.runner import ROOT
from sipp_baseline.validation import oracle, validate


class OnDemandTests(unittest.TestCase):
    def test_rebase_witnesses_and_reject_changed_empty_actions(self):
        subprocess.run(['make','build/on_demand','build-adaptive'],cwd=ROOT,
                       capture_output=True,check=True)
        q = dict(grid=['.'*13],start=[0,0,0,0],goal=[0,12,0],horizon=170)
        barrier = [[0,9,0,170],[0,4,55,65]]
        sequence = [(dict(q,start_tick=0),barrier),
                    (dict(q,start_tick=1),barrier),
                    (dict(q,start_tick=2),[]),
                    (dict(q,start_tick=42,start=[0,4,0,1]),[[0,7,48,63]]),
                    (dict(q,start_tick=43,start=[0,4,0,1]),[]),
                    (dict(q,start_tick=44,start=[0,4,0,1],horizon=110),[]),
                    (dict(q,start_tick=45,grid=['........#....']),[])]
        queries = [(query,dict(reservations=reservations)) for query,reservations in sequence]
        payload = ''.join(protocol(query,f,100000) for query,f in queries)
        def run(name):
            proc = subprocess.run([ROOT/'build'/name,'0','5','--suffix-fresh'],input=payload,
                                  text=True,capture_output=True,check=True)
            return [json.loads(line) for line in proc.stdout.splitlines()]
        candidate, baseline = run('on_demand'), run('sipp_ip_adaptive')
        self.assertEqual(len(candidate),len(queries))
        self.assertGreater(candidate[1]['clipped_hits'],0)
        self.assertEqual(candidate[1]['status'],'no_path')
        self.assertEqual(candidate[2]['status'],'solved')
        for (query,f),result,ref in zip(queries,candidate,baseline):
            self.assertEqual((result['status'],result['cost_ticks']),oracle(query,f))
            self.assertEqual(result['steps'],ref['steps'])
            self.assertEqual(result['expansions'],ref['expansions'])
            validate(query,f,result)

    def test_turn_and_brake_waiting_intervals(self):
        subprocess.run(['make','build/on_demand'],cwd=ROOT,capture_output=True,check=True)
        data = dict(grid=['.'*9]*9,start=[0,0,0,0],goal=[8,8,0],horizon=240)
        # Reach the corner moving east, brake, turn south and brake again.
        # A change at the brake destination can shorten a waiting interval.
        initial = [[8,8,155,178]]
        queries = [(dict(data,start_tick=0),dict(reservations=initial)),
                   (dict(data,start_tick=41,start=[0,4,0,1]),dict(reservations=[])),
                   (dict(data,start_tick=42,start=[0,4,0,1]),dict(reservations=[[0,8,90,110]])),
                   (dict(data,start_tick=43,start=[0,4,0,1]),dict(reservations=initial))]
        payload = ''.join(protocol(q,f,100000) for q,f in queries)
        proc = subprocess.run([ROOT/'build/on_demand','0','5','--suffix-fresh'],input=payload,
                              text=True,capture_output=True,check=True)
        rows = list(map(json.loads,proc.stdout.splitlines()))
        self.assertEqual(len(rows),len(queries))
        self.assertGreater(sum(row.get('batch_hits',0) for row in rows),0)
        for (q,f),row in zip(queries,rows):
            self.assertEqual((row['status'],row['cost_ticks']),oracle(q,f))
            validate(q,f,row)
