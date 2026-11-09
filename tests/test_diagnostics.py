import copy
import json
from pathlib import Path
import random
import tempfile
import unittest

from test_baseline import scenario
from sipp_baseline.controlled import MODES, controlled_cases, mutate, render_controlled
from sipp_baseline.diagnostics import change_size
from sipp_baseline.generate import canonical, obstacle_reservations
from sipp_baseline.model import load
from sipp_baseline.repair import compare_case, solve_incremental
from sipp_baseline.runner import ROOT
from sipp_baseline.validation import oracle, validate


def tiny_base():
    obstacle={'id':0,'start':[2,0],'goal':[2,4],'base_step_ticks':30,
              'nodes':[[2,c,c*30] for c in range(5)],'extra_reservations':[]}
    other={'id':1,'start':[3,0],'goal':[3,0],'base_step_ticks':30,
           'nodes':[[3,0,0]],'extra_reservations':[]}
    data=scenario(grid=['.'*13]*4,horizon=240,start=[0,0,0,0],goal=[0,12,0])
    data['forecasts'][0].update({'obstacles':[obstacle,other],
        'reservations':canonical(obstacle_reservations(obstacle,240)+obstacle_reservations(other,240),240)})
    data['metadata']={'seed':7,'map_name':'fixture','obstacle_interaction_policy':'independent','change_probability':0}
    return data


class DiagnosticTests(unittest.TestCase):
    def test_exact_locality_against_enumerated_cell_ticks(self):
        rng=random.Random(777)
        for _ in range(100):
            data=scenario(grid=['..#','...'],horizon=20,start=[0,0,0,0],goal=[1,2,0])
            snapshots=[{'reservations':[[rng.randrange(2),rng.randrange(3),a,min(20,a+rng.randrange(7))]
                        for a in [rng.randrange(21) for _ in range(12)]]} for _ in range(2)]
            sets=[{(r,c,t) for r,c,a,b in f['reservations'] if data['grid'][r][c]=='.' for t in range(a,b+1)} for f in snapshots]
            difference=sets[0]^sets[1];metrics=change_size(data,*snapshots)
            self.assertEqual(metrics['changed_cell_ticks'],len(difference))
            self.assertEqual(metrics['reservation_changed_cells'],len({(r,c) for r,c,t in difference}))
            self.assertEqual(metrics['change_first_tick'],min((t for r,c,t in difference),default=None))
            self.assertEqual(metrics['change_last_tick'],max((t for r,c,t in difference),default=None))

    def test_native_lifecycle_counters_across_retirement_compaction_and_reuse(self):
        data=load(ROOT/'examples/corridor.json')
        rows=solve_incremental(data)
        for f,r in zip(data['forecasts'],rows):
            validate(data,f,r)
            self.assertEqual(r['live_labels'],r['before_live_labels']-r['retired_labels']+r['created_labels'])
            self.assertEqual(r['live_owners'],r['before_live_owners']-r['retired_owners']+r['expansions'])
            self.assertEqual(r['covered_states'],r['before_covered_states']-r['retired_states']+r['expanded_states'])
            self.assertEqual(r['live_projections'],r['before_live_projections']-r['retired_projections']+r['projections']-r['changed_projections']-r['reused_projections'])
            self.assertLessEqual(r['direct_invalidated_labels'],r['retired_labels'])
            for key in ('recheck_us','retirement_us','coverage_restore_us','installation_us'):
                self.assertGreaterEqual(r[key],0)
        self.assertTrue(any(r['retired_projections'] for r in rows))

    def test_four_variants_are_isolated_causal_and_do_not_mutate_base(self):
        base=tiny_base();original=copy.deepcopy(base);cases=controlled_cases(base,revision_tick=10)
        self.assertEqual(base,original)
        self.assertEqual({c['metadata']['controlled_mode'] for c in cases},set(MODES))
        ids={c['metadata']['controlled_event']['obstacle'] for c in cases}
        boundaries={c['metadata']['controlled_event']['effective_tick'] for c in cases}
        self.assertEqual(len(ids),1);self.assertEqual(len(boundaries),1)
        for data in cases:
            before=data['metadata']['changed_obstacle_before'];after=data['metadata']['changed_obstacle_after']
            self.assertEqual(before['start'],after['start']);self.assertEqual(before['goal'],after['goal'])
            self.assertEqual(before['extra_reservations'],after['extra_reservations'])
            self.assertNotIn('change_probability',data['metadata'])
            self.assertGreater(change_size(data,*data['forecasts'])['change_first_tick'],10)
            others=[o for o in base['forecasts'][0]['obstacles'] if o['id']!=before['id']]
            self.assertEqual(data['forecasts'][1]['reservations'],canonical([row for o in [*others,after] for row in obstacle_reservations(o,240)],240))
            for a,b in zip(after['nodes'],after['nodes'][1:]):
                self.assertGreater(b[2],a[2]);self.assertLessEqual(max(abs(a[0]-b[0]),abs(a[1]-b[1])),1)
            moving=lambda o:[b[2]-a[2] for a,b in zip(o['nodes'],o['nodes'][1:]) if a[:2]!=b[:2]]
            old,new=moving(before),moving(after);mode=data['metadata']['controlled_mode']
            if mode in ('accelerate-one-edge','decelerate-one-edge'):
                self.assertEqual(sum(a!=b for a,b in zip(old,new)),1)
                self.assertEqual(sum(new)-sum(old),-10 if mode=='accelerate-one-edge' else 10)
            elif mode=='pause-10':self.assertEqual(old,new)
            else:self.assertEqual(len(new),len(old)+1)
            for f,r in zip(data['forecasts'],solve_incremental(data)):
                validate(data,f,r);self.assertEqual((r['status'],r['cost_ticks']),oracle(data,f))
        self.assertEqual(controlled_cases(base,10),cases)
        base['metadata']['obstacle_interaction_policy']='prioritized'
        prioritized=controlled_cases(base,10)
        self.assertEqual(len(prioritized),4)
        for data in prioritized:
            changed=data['metadata']['changed_obstacle_after']
            occupied=lambda o:{(r,c,t) for r,c,a,b in obstacle_reservations(o,240) for t in range(a,b+1)}
            for other in base['forecasts'][0]['obstacles']:
                if other['id']!=changed['id']:self.assertFalse(occupied(other)&occupied(changed))

    def test_no_eligible_group_is_reported_without_forcing_changes(self):
        base=tiny_base()
        for o in base['forecasts'][0]['obstacles']:o['nodes']=[o['nodes'][-1]]
        self.assertEqual(controlled_cases(base,100),[])
        with self.assertRaises(ValueError):mutate(tiny_base()['forecasts'][0]['obstacles'][0],0,'unknown')

    def test_comparison_exports_diagnostics_and_controlled_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);data=controlled_cases(tiny_base(),10)[0]
            case=output/'case';case.mkdir();source=case/'scenario.json';source.write_text(json.dumps(data))
            summary=compare_case(source,case/'comparison',repeats=1,warmups=0,check_oracle=True)
            self.assertIsNotNone(summary['diagnostics']['retained_coverage_fraction'])
            self.assertIn('changed_cell_ticks',(case/'comparison/comparison.csv').read_text())
            (output/'controlled-suite.json').write_text(json.dumps({'runs':[{'map':'fixture','seed':7,
                'mode':MODES[0],'directory':'case','obstacle':0,'effective_tick':30,**summary}],'unavailable':[]}))
            render_controlled(output)
            self.assertIn('Cascade amplification',(output/'index.html').read_text())
            self.assertTrue((output/'diagnostics.csv').exists())
