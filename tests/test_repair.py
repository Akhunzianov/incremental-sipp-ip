import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from test_baseline import scenario
from sipp_baseline.model import load, protocol
from sipp_baseline.repair import classify_pair, compare_case, compare_suite, ensure_incremental, solve_incremental
from sipp_baseline.runner import ROOT, solve_batch
from sipp_baseline.validation import oracle, validate


class RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_incremental()

    def check(self,data,use_oracle=True):
        baseline=solve_batch(data)
        incremental=solve_incremental(data)
        for forecast,a,b in zip(data['forecasts'],baseline,incremental):
            self.assertEqual((a['status'],a['cost_ticks']),(b['status'],b['cost_ticks']),
                             msg=json.dumps({'scenario':data,'forecast':forecast['id'],'baseline':a,'repair':b}))
            validate(data,forecast,b)
            if use_oracle:
                self.assertEqual((b['status'],b['cost_ticks']),oracle(data,forecast))
        return incremental

    def test_corridor_block_unblock_and_empty_projection(self):
        rows=self.check(load(ROOT/'examples/corridor.json'))
        self.assertEqual([r['cost_ticks'] for r in rows],[100,126,100,None,100])
        self.assertTrue(any(r['changed_projections'] for r in rows[1:]))
        self.assertGreater(rows[-1]['created_labels'],0)
        self.assertTrue(any(r['compactions'] for r in rows[1:]))

    def test_unchanged_effective_union_does_no_search(self):
        forecasts=[{'id':str(i),'reservations':r} for i,r in enumerate([
            [[0,6,0,70]],[[0,6,0,30],[0,6,25,70],[0,6,30,70]],[[0,6,0,70]]])]
        rows=self.check(scenario(forecasts=forecasts,horizon=220))
        for row in rows[1:]:
            self.assertTrue(row['unchanged_forecast'])
            self.assertEqual(row['expansions'],0)
            self.assertEqual(row['projections'],0)
            self.assertFalse(row['reset'])

    def test_feasible_old_path_does_not_hide_new_shortcut(self):
        data=scenario(grid=['.'*9]*9,horizon=240,forecasts=[
            {'id':'long','reservations':[[0,4,0,240]]},
            {'id':'shortcut','reservations':[]}])
        rows=self.check(data)
        self.assertEqual([r['cost_ticks'] for r in rows],[200,180])

    def test_root_changes_invalid_start_cycles_and_restoration(self):
        data=scenario(horizon=220,forecasts=[{'id':str(i),'reservations':r} for i,r in enumerate([
            [],[[0,0,1,220]],[[0,0,0,220]],[[0,0,1,220]],[],[]])])
        rows=self.check(data)
        self.assertEqual([r['status'] for r in rows],['solved','no_path','invalid_start','no_path','solved','solved'])
        self.assertEqual(rows[-1]['expansions'],0)

    def test_split_merge_waiting_and_departure_boundaries(self):
        changes=[[],[[0,6,30,50]],[[0,6,30,70]],[[0,6,30,40],[0,6,60,70]],
                 [[0,12,100,110]],[[0,12,100,100]],[[0,10,150,150]],
                 [[0,4,40,40]],[[0,4,41,41]],[]]
        self.check(scenario(horizon=240,forecasts=[{'id':str(i),'reservations':r} for i,r in enumerate(changes)]))

    def test_dormant_alternatives_are_reactivated_after_owner_loss(self):
        data=scenario(grid=['.'*13]*13,horizon=600,forecasts=[
            {'id':'delayed-goal','reservations':[[12,12,0,400]]},
            {'id':'lost-branch','reservations':[[12,12,0,400],[0,4,0,600]]}])
        rows=self.check(data)
        self.assertEqual([r['cost_ticks'] for r in rows],[421,421])
        self.assertGreater(rows[1]['retired_owners'],0)
        self.assertGreater(rows[1]['reactivated_intervals'],0)

    def test_moving_start_nonzero_start_tick_and_terminal_root(self):
        for start,goal,start_tick,horizon in [([0,0,0,1],[0,4,0],7,100),([0,0,0,0],[0,0,0],0,0)]:
            data=scenario(start=start,goal=goal,horizon=horizon)
            data['start_tick']=start_tick
            data['forecasts']*=2
            data['forecasts']=[{**f,'id':str(i)} for i,f in enumerate(data['forecasts'])]
            self.check(data)

    def test_budget_exit_preserves_frontier_and_is_not_a_certificate(self):
        data=scenario(horizon=220)
        payload=protocol(data,data['forecasts'][0],0)+protocol(data,data['forecasts'][0],100000)
        result=subprocess.run([str(ensure_incremental())],input=payload,text=True,capture_output=True,check=True)
        rows=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]['status'],'expansion_limit')
        self.assertEqual((rows[1]['status'],rows[1]['cost_ticks']),('solved',100))
        self.assertFalse(rows[1]['reset'])

    def test_query_changes_reset_persistent_storage(self):
        a=scenario(horizon=220)
        b=scenario(grid=['.'*9]*9,horizon=240)
        payload=protocol(a,a['forecasts'][0],100000)+protocol(b,b['forecasts'][0],100000)
        result=subprocess.run([str(ensure_incremental())],input=payload,text=True,capture_output=True,check=True)
        rows=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(all(r['reset'] for r in rows))
        self.assertEqual([r['cost_ticks'] for r in rows],[100,180])

    def test_randomized_repeated_updates_against_oracle(self):
        # Fixed query per sequence, mixed insertions/removals, repeated snapshots,
        # overlapping intervals, ties, roots, cycles and dormant alternatives.
        for seed in range(80):
            rng=random.Random(seed)
            h,w=rng.choice([(1,13),(9,9),(5,13)])
            horizon=240
            grid=[''.join('#' if rng.random()<.015 else '.' for _ in range(w)) for _ in range(h)]
            grid[0]='.'+grid[0][1:];grid[-1]=grid[-1][:-1]+'.'
            reservations=[];forecasts=[]
            for revision in range(10):
                if revision%4!=0:
                    reservations=[r for r in reservations if rng.random()<.55]
                    for _ in range(rng.randrange(1,9)):
                        a=rng.randrange(201)
                        reservations.append([rng.randrange(h),rng.randrange(w),a,min(horizon,a+rng.randrange(1,70))])
                forecasts.append({'id':str(revision),'reservations':[r.copy() for r in reservations]})
            data=scenario(grid=grid,forecasts=forecasts,horizon=horizon,start=[0,0,rng.randrange(4),0])
            with self.subTest(seed=seed):
                self.check(data)

    def test_differential_report_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary=compare_case(ROOT/'examples/corridor.json',Path(tmp)/'comparison',repeats=2,warmups=1,check_oracle=True)
            self.assertEqual(summary['verdicts'],{'matched':5})
            self.assertTrue((Path(tmp)/'comparison/comparison.csv').exists())
        self.assertEqual(classify_pair({'status':'solved','cost_ticks':100},{'status':'expansion_limit','cost_ticks':None}),'inconclusive')

    def test_resume_rejects_changed_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'suite';case=source/'map/q-0';case.mkdir(parents=True)
            original=(ROOT/'examples/corridor.json').read_text()
            (case/'scenario.json').write_text(original)
            (source/'suite.json').write_text(json.dumps({'complete':True,'runs':[
                {'map':'demo','q':0,'forecasts':[{'view':'map/q-0/viewer.html'}]}]}))
            output=Path(tmp)/'comparison'
            compare_suite(source,output,repeats=1,warmups=0)
            compare_suite(source,output,repeats=1,warmups=0,resume=True)
            changed=json.loads(original)
            changed['forecasts'][0]['reservations'].append([0,0,0,0])
            (case/'scenario.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'changed inputs or planner'):
                compare_suite(source,output,repeats=1,warmups=0,resume=True)
