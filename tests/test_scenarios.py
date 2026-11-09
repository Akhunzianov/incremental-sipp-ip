import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from sipp_baseline.generate import generate
from sipp_baseline.model import load
from sipp_baseline.obstacle_routes import StaticRoutes
from sipp_baseline.repair import solve_incremental
from sipp_baseline.runner import ROOT,solve_batch
from sipp_baseline.scenario_cases import PROFILES, build_profile, engineered_cases, select_obstacles
from sipp_baseline.scenario_cases import reservations
from sipp_baseline.scenario_suite import audit_trace, classify_transition, compare_scenarios, save_case, write_json
from sipp_baseline.validation import oracle, validate
from sipp_baseline.local_scenarios import mutate_local,build_local_profile
from sipp_baseline.diagnostics import change_size


class DiverseScenarioTests(unittest.TestCase):
    def test_bounded_pulses_really_invalidate_old_paths(self):
        root=ROOT/'examples/diverse-pulses';suite=json.loads((root/'suite.json').read_text())
        for case in suite['cases']:
            folder=root/case['directory'];data=load(folder/'scenario.json')
            trace=json.loads(gzip.decompress((folder/'trajectory-changes.json.gz').read_bytes()))
            audit_trace(data,data['metadata']['initial_obstacles'],trace,True)
            baseline=solve_batch(data);incremental=solve_incremental(data)
            with self.assertRaises(ValueError):validate(data,data['forecasts'][1],baseline[0])
            self.assertGreater(baseline[1]['cost_ticks'],baseline[0]['cost_ticks'])
            size=change_size(data,*data['forecasts'])
            self.assertLessEqual(size['reservation_changed_cells'],3*case['total_obstacles'])
            self.assertGreaterEqual(size['change_first_tick'],40)
            self.assertLessEqual(size['change_last_tick'],max(o['nodes'][-1][2] for o in data['metadata']['initial_obstacles']))
            for change in trace[0]['changes']:
                self.assertEqual(change['before']['nodes'][-1],change['after']['nodes'][-1])
            for f,a,b in zip(data['forecasts'],baseline,incremental):
                self.assertEqual((a['status'],a['cost_ticks']),oracle(data,f))
                self.assertEqual((a['status'],a['cost_ticks']),(b['status'],b['cost_ticks']))

    def test_local_edits_preserve_deadlines_and_bounded_support(self):
        base={'grid':['.'*13]*9,'horizon':400}
        old={'id':0,'start':[3,0],'goal':[3,6],'base_step_ticks':40,'extra_reservations':[],
             'nodes':[[3,c,c*40] for c in range(7)]}
        from sipp_baseline.generate import obstacle_reservations
        for waypoint in (None,(2,3)):
            new=mutate_local(old,3,waypoint)
            self.assertEqual(new['nodes'][5:],old['nodes'][4:])
            self.assertEqual(new['nodes'][:4],old['nodes'][:4])
            size=change_size(base,{'reservations':obstacle_reservations(old,400)},
                                  {'reservations':obstacle_reservations(new,400)})
            self.assertLessEqual(size['reservation_changed_cells'],3)
            self.assertGreaterEqual(size['change_first_tick'],111)
            self.assertLessEqual(size['change_last_tick'],169)

    def test_local_profile_trace_support_and_paired_geometry(self):
        base=generate(['.'*13]*9,seed=7,updates=0,obstacles=12,change_probability=0)
        for level in ('few','many'):
            for geometry in ('cluster','spread'):
                data,trace=build_local_profile(base,level,geometry)
                audit_trace(data,base['forecasts'][0]['obstacles'],trace)
                self.assertLessEqual(data['metadata']['changed_cells'],3*len(trace[0]['changes']))
                self.assertTrue(data['metadata']['deadline_preserved'])
                self.assertEqual(build_local_profile(base,level,geometry)[0],data)

    def test_spatial_selection_and_requested_counts(self):
        import random
        plans=[{'id':i,'nodes':[[r,c,500],[r,c+1,600]]}
               for i,(r,c) in enumerate([(0,0),(0,1),(1,0),(1,1),(10,10),(10,11),(11,10),(11,11)])]
        cluster,positions,requested=select_obstacles(plans,100,'few','cluster',random.Random(1))
        spread,_,_=select_obstacles(plans,100,'few','spread',random.Random(1))
        diameter=lambda ids:max(abs(positions[a][0]-positions[b][0])+abs(positions[a][1]-positions[b][1]) for a in ids for b in ids)
        self.assertEqual(requested,4);self.assertEqual(len(cluster),4)
        self.assertLess(diameter(cluster),diameter(spread))
        self.assertEqual(len(select_obstacles(plans,100,'all','spread',random.Random(1))[0]),8)
        self.assertEqual(select_obstacles(plans,700,'few','cluster',random.Random(1))[0],[])

    def test_profiles_reconstruct_causal_histories_without_mutating_base(self):
        base=generate(['.'*13]*9,seed=7,updates=0,obstacles=12,change_probability=0)
        original=copy.deepcopy(base);reference=solve_batch(base)[0]
        forbidden={tuple(base['start'][:2]),tuple(base['goal'][:2])}
        with StaticRoutes(base['grid'],forbidden) as router:
            for spec in PROFILES:
                with self.subTest(profile=spec[0]):
                    data,trace=build_profile(base,spec,reference,router.via)
                    audit_trace(data,base['forecasts'][0]['obstacles'],trace)
                    self.assertEqual(base,original)
                    self.assertTrue(all(set(f['changed_ids'])<=set(data['metadata']['selected_ids']) for f in data['forecasts'][1:]))
                    if spec[-1]=='alternating':
                        self.assertEqual(data['forecasts'][0]['reservations'],data['forecasts'][2]['reservations'])
                        self.assertEqual(data['forecasts'][0]['reservations'],data['forecasts'][4]['reservations'])
                        self.assertEqual(data['forecasts'][1]['reservations'],data['forecasts'][3]['reservations'])
                    if spec[-1]=='repeated':self.assertEqual([f['revision_tick'] for f in data['forecasts'][1:]],[100,140,310])

    def test_engineered_outcomes_against_both_planners_and_oracle(self):
        labels=set()
        for data,initial,trace in engineered_cases(7,2):
            audit_trace(data,initial,trace)
            baseline=solve_batch(data);incremental=solve_incremental(data)
            for f,a,b in zip(data['forecasts'],baseline,incremental):
                self.assertEqual((a['status'],a['cost_ticks']),oracle(data,f))
                self.assertEqual((a['status'],a['cost_ticks']),(b['status'],b['cost_ticks']))
                validate(data,f,b)
            for f,old,new in zip(data['forecasts'][1:],baseline,baseline[1:]):
                labels.add(classify_transition(data,f,old,new)['outcome'])
        self.assertTrue({'old_path_stays_optimal','shorter_path','old_path_invalid','no_path','recovery'}<=labels)

    def test_trace_rejects_hidden_obstacle_changes(self):
        data,initial,trace=engineered_cases(11,4)[0]
        bad=copy.deepcopy(trace);bad[0]['changes'][0]['after']['start']=[0,0]
        with self.assertRaises(ValueError):audit_trace(data,initial,bad)
        bad=copy.deepcopy(trace);bad[0]['changes'].pop()
        with self.assertRaises(ValueError):audit_trace(data,initial,bad)

    def test_source_overlaps_are_preserved_but_new_conflicts_rejected(self):
        data,initial,trace=engineered_cases(7,2)[0]
        duplicate=copy.deepcopy(initial[0]);duplicate['id']=99;initial.append(duplicate)
        final=[c['after'] for c in trace[0]['changes']]+[duplicate]
        data['forecasts'][0]['reservations']=reservations(initial,400)
        data['forecasts'][1]['reservations']=reservations(final,400)
        metrics=audit_trace(data,initial,trace,True)
        self.assertGreater(metrics['inherited_conflict_cell_pairs'],0)
        before=initial[0];cell=before['nodes'][2][:2];start=before['nodes'][-1][2]+10
        newcomer={'id':100,'start':cell,'goal':cell,'base_step_ticks':20,'extra_reservations':[],'nodes':[[*cell,start]]}
        initial.append(newcomer);final.append(newcomer)
        data['forecasts'][0]['reservations']=reservations(initial,400)
        data['forecasts'][1]['reservations']=reservations(final,400)
        with self.assertRaisesRegex(ValueError,'new prioritized'):audit_trace(data,initial,trace,True)

    def test_saved_suite_comparison_coverage_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';source.mkdir();cases=[]
            for data,initial,trace in engineered_cases(7,2):
                name=data['metadata']['profile']
                cases.append(save_case(source,name,data,initial,trace,
                    {'tier':'engineered','map':name,'seed':7,'density':data['metadata']['obstacle_density'],'profile':name}))
                saved=load(source/name/'scenario.json')
                decoded=json.loads(gzip.decompress((source/name/'trajectory-changes.json.gz').read_bytes()))
                audit_trace(saved,initial,decoded)
            write_json(source/'suite.json',{'complete':True,'config':{},'cases':cases})
            output=Path(tmp)/'comparison'
            index=compare_scenarios(source,output)
            coverage=json.loads((output/'coverage.json').read_text())
            self.assertEqual(coverage['cases'],6);self.assertEqual(coverage['verdicts'],{'matched':16})
            self.assertGreater(coverage['observed_outcomes']['no_path'],0)
            self.assertTrue(index.exists());self.assertTrue((output/'events.csv').exists())
            compare_scenarios(source,output,resume=True)
            with self.assertRaises(ValueError):compare_scenarios(source,output,repeats=2,resume=True)

    def test_resource_limits_remain_inconclusive(self):
        data,_,_=engineered_cases(7,2)[0]
        limited={'status':'expansion_limit','cost_ticks':None,'steps':[]}
        self.assertEqual(classify_transition(data,data['forecasts'][1],limited,limited)['outcome'],'inconclusive')
