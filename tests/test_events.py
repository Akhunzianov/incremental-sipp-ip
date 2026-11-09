import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_baseline import scenario
from sipp_baseline.events import POLICY, planning_events
from sipp_baseline.repair import compare_case, compare_suite
from sipp_baseline.runner import benchmark, solve_batch
from sipp_baseline.visualize import viewer_data


class PredictionEventTests(unittest.TestCase):
    def test_effective_unions_not_formatting_metadata_or_static_walls(self):
        data=scenario(grid=['.'*12+'#'],horizon=220,forecasts=[
            {'id':'a','reservations':[[0,6,0,70]]},
            {'id':'b','reservations':[[0,6,31,70],[0,6,0,30],[0,6,0,20],[0,12,0,200]],'events':[{'outcome':'applied'}]},
            {'id':'c','reservations':[[0,6,0,71]]},
            {'id':'d','reservations':[[0,6,0,70]]}])
        selected,events=planning_events(data)
        self.assertEqual([f['id'] for f in selected],['a','c','d'])
        self.assertFalse(events[1]['planner_invoked'])
        self.assertEqual(events[1]['source_forecast_id'],'a')

    def test_comparison_sends_only_changes_to_both_planners(self):
        data=scenario(horizon=220,forecasts=[
            {'id':name,'revision_tick':tick,'reservations':rs}
            for name,tick,rs in [('a',0,[]),('same',13,[]),('blocked',57,[[0,6,0,70]]),
                                 ('same-again',58,[[0,6,0,30],[0,6,31,70]]),('restored',211,[])]])
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'scenario.json';source.write_text(json.dumps(data))
            output=Path(tmp)/'comparison'
            with patch('sipp_baseline.repair.solve_batch',wraps=solve_batch) as solver:
                summary=compare_case(source,output,repeats=1,warmups=0,check_oracle=True)
            self.assertEqual(solver.call_count,2)
            for call in solver.call_args_list:
                self.assertEqual([f['id'] for f in call.args[0]['forecasts']],['a','blocked','restored'])
            self.assertEqual((summary['received_forecasts'],summary['skipped_forecasts'],summary['queries'],summary['replanning_events']),(5,2,3,2))
            events=json.loads((output/'events.json').read_text())
            self.assertEqual([e['revision_tick'] for e in events if e['planner_invoked']],[0,57,211])
            self.assertEqual(summary['verdicts'],{'matched':3})

    def test_q_zero_report_has_no_replans_or_speedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'suite';case=source/'map/q-0';case.mkdir(parents=True)
            data=scenario(forecasts=[{'id':str(i),'reservations':[]} for i in range(6)])
            (case/'scenario.json').write_text(json.dumps(data))
            (source/'suite.json').write_text(json.dumps({'complete':True,'runs':[
                {'map':'demo','q':0,'forecasts':[{'view':'map/q-0/viewer.html'}]}]}))
            output=Path(tmp)/'comparison'
            index=compare_suite(source,output,repeats=1,warmups=0)
            row=json.loads((output/'suite-summary.json').read_text())['runs'][0]
            self.assertEqual((row['queries'],row['replanning_events'],row['skipped_forecasts']),(1,0,5))
            self.assertIsNone(row['updates']['speedup'])
            self.assertEqual(row['updates']['baseline_total_us'],0)
            self.assertIn('no replans',index.read_text())
            compare_suite(source,output,repeats=1,warmups=0,resume=True)
            manifest_path=output/'map/q-0/manifest.json'
            manifest=json.loads(manifest_path.read_text())
            manifest['driver_sha256']['sipp_baseline/events.py']='old-driver'
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'policy or driver'):
                compare_suite(source,output,repeats=1,warmups=0,resume=True)
            old_summary=json.loads((output/'suite-summary.json').read_text())
            old_summary['config'].pop('evaluation_policy')
            (output/'suite-summary.json').write_text(json.dumps(old_summary))
            with self.assertRaisesRegex(ValueError,'settings differ'):
                compare_suite(source,output,repeats=1,warmups=0,resume=True)

    def test_baseline_skips_queries_but_viewer_preserves_observations(self):
        data=scenario(forecasts=[{'id':str(i),'reservations':[]} for i in range(3)])
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'run'
            with patch('sipp_baseline.runner.solve_batch',wraps=solve_batch) as solver:
                summary=benchmark(data,output,repeats=1,warmups=0,check_oracle=True)
            self.assertEqual(len(solver.call_args.kwargs['forecasts']),1)
            self.assertEqual([s['planner_invoked'] for s in summary],[True,False,False])
            self.assertEqual([s['samples'] for s in summary],[1,0,0])
            self.assertEqual(json.loads((output/'aggregate.json').read_text())['updates']['queries'],0)
            view=viewer_data(output)
            self.assertEqual(len(view['forecasts']),3)
            self.assertEqual(view['forecasts'][-1]['result']['source_forecast_id'],'0')
            self.assertFalse(view['forecasts'][-1]['result']['planner_invoked'])
            self.assertEqual(json.loads((output/'manifest.json').read_text())['evaluation_policy'],POLICY)

    def test_independent_instances_are_not_deduplicated(self):
        data=scenario(forecasts=[{'id':str(i),'reservations':[]} for i in range(3)])
        data['metadata']={'independent_instances':True}
        self.assertEqual(len(planning_events(data)[0]),3)
        with tempfile.TemporaryDirectory() as tmp:
            with patch('sipp_baseline.runner.solve_batch',wraps=solve_batch) as solver:
                benchmark(data,Path(tmp)/'run',repeats=1,warmups=0)
            self.assertEqual(len(solver.call_args.kwargs['forecasts']),3)
