"""Executable checks of the invariants used in docs/repair-correctness.md.

The audits share projection code with the planner; independent oracle checks
are kept alongside them. Neither is a substitute for the mathematical proof.
"""
import json
import random
import subprocess
import unittest

from test_baseline import scenario
from sipp_baseline.model import load, protocol
from sipp_baseline.repair import solve_incremental
from sipp_baseline.runner import ROOT
from sipp_baseline.validation import oracle, validate


class RepairProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=ROOT/'build/sipp_ip_incremental_verified'
        cls.rollover=ROOT/'build/sipp_ip_repair_rollover'
        cls.binary.parent.mkdir(exist_ok=True)
        for source,target in [('src/incremental.cpp',cls.binary),('tests/repair_rollover.cpp',cls.rollover)]:
            subprocess.run(['g++','-std=c++17','-O1','-Wall','-Wextra','-Wpedantic',
                            '-DSIPP_REPAIR_VERIFY',str(ROOT/source),'-o',str(target)],check=True)

    def check(self,data):
        rows=solve_incremental(data,binary=self.binary)
        self.assertEqual(len(rows),len(data['forecasts']))
        for forecast,row in zip(data['forecasts'],rows):
            validate(data,forecast,row)
            self.assertEqual((row['status'],row['cost_ticks']),oracle(data,forecast))
        return rows

    def test_audited_arbitrary_updates_moving_starts_and_goals(self):
        # Distinct seeds from the original 800-query differential test.
        for seed in range(1000,1060):
            rng=random.Random(seed);h,w=rng.choice([(1,13),(9,9),(5,13)])
            reservations=[];forecasts=[];horizon=240
            for revision in range(8):
                if revision%3!=2:
                    reservations=[r for r in reservations if rng.random()<.45]
                    for _ in range(rng.randrange(12)):
                        a=rng.randrange(horizon+1)
                        reservations.append([rng.randrange(h),rng.randrange(w),a,min(horizon,a+rng.randrange(50))])
                forecasts.append({'id':str(revision),'reservations':[r.copy() for r in reservations]})
            data=scenario(grid=['.'*w]*h,horizon=horizon,start=[0,0,rng.choice([0,3]),rng.randrange(2)],
                          goal=[h-1,w-1,rng.randrange(2)],forecasts=forecasts)
            data['start_tick']=rng.randrange(11)
            with self.subTest(seed=seed):self.check(data)

    def test_audited_owner_loss_repeated_compaction_and_restoration(self):
        changes=[[],[[0,4,0,600]],[],[[4,0,0,600]],[[0,0,0,600]],[],[]]
        data=scenario(grid=['.'*13]*13,horizon=600,forecasts=[
            {'id':str(i),'reservations':[[12,12,0,400],*rs]} for i,rs in enumerate(changes)])
        rows=self.check(data)
        self.assertTrue(any(r['reactivated_intervals'] for r in rows))
        self.assertGreater(sum(r['compactions'] for r in rows),1)

    def test_audited_budget_interruptions_with_changed_forecasts(self):
        data=load(ROOT/'examples/corridor.json');pairs=[]
        for i,forecast in enumerate(data['forecasts']):
            for budget in [0,1,0,2,100000]:pairs.append((forecast,budget))
        payload=''.join(protocol(data,f,budget) for f,budget in pairs)
        result=subprocess.run([str(self.binary)],input=payload,text=True,capture_output=True,check=True)
        rows=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows),len(pairs))
        for (forecast,budget),row in zip(pairs,rows):
            validate(data,forecast,row)
            if row['status']!='expansion_limit':
                self.assertEqual((row['status'],row['cost_ticks']),oracle(data,forecast))
            if budget==100000:self.assertNotEqual(row['status'],'expansion_limit')

    def test_stamp_rollover_and_storage_bound(self):
        data=load(ROOT/'examples/corridor.json')
        payload=''.join(protocol(data,f,100000) for f in data['forecasts'][:2])
        result=subprocess.run([str(self.rollover)],input=payload,text=True,capture_output=True,check=True)
        self.assertEqual(result.stdout.strip(),'solved 126')
