"""Build and differential-test persistent interval repair against full replanning."""
from collections import Counter
import csv
import hashlib
import html
import json
from pathlib import Path
import statistics
import subprocess

from .model import load
from .events import POLICY, planning_events
from .diagnostics import PHASES, COUNTERS, change_size, repair_metrics, aggregate_diagnostics
from .runner import ROOT, ensure_built, solve_batch
from .validation import oracle, validate

INCREMENTAL = ROOT/'build/sipp_ip_incremental'
FLAGS = ['-std=c++17','-O3','-DNDEBUG','-Wall','-Wextra','-Wpedantic']


def build_incremental():
    INCREMENTAL.parent.mkdir(exist_ok=True)
    subprocess.run(['g++',*FLAGS,str(ROOT/'src/incremental.cpp'),'-o',str(INCREMENTAL)],check=True)
    return INCREMENTAL


def ensure_incremental():
    if not INCREMENTAL.exists() or any((ROOT/p).stat().st_mtime>INCREMENTAL.stat().st_mtime
                                      for p in ('src/incremental.cpp','src/model.hpp')):
        build_incremental()
    return INCREMENTAL


def solve_incremental(scenario, max_expansions=1_000_000, timeout=120, binary=None):
    return solve_batch(scenario,max_expansions=max_expansions,timeout=timeout,
                       binary=ensure_incremental() if binary is None else binary)


def classify_pair(a,b):
    if 'expansion_limit' in (a['status'],b['status']):
        return 'inconclusive'
    return 'matched' if (a['status'],a['cost_ticks'])==(b['status'],b['cost_ticks']) else 'mismatch'


def scenario_digest(scenario):
    digest = hashlib.sha256()
    for chunk in json.JSONEncoder(sort_keys=True,separators=(',',':')).iterencode(scenario):
        digest.update(chunk.encode())
    return digest.hexdigest()


def compare_case(scenario_path, output, repeats=3, warmups=1, max_expansions=2_000_000,
                 timeout=120, check_oracle=False):
    source = Path(scenario_path).resolve()
    scenario = load(source)
    selected,decisions = planning_events(scenario)
    query_scenario = {**scenario,'forecasts':selected}
    output = Path(output)
    if output.exists():
        raise ValueError(f'output already exists: {output}')
    output.mkdir(parents=True)
    binaries = {'baseline':ensure_built(),'incremental':ensure_incremental()}
    sources = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
               for p in ('src/planner.cpp','src/incremental.cpp','src/model.hpp','src/fresh.hpp')}
    try:
        revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except subprocess.CalledProcessError:
        revision = None
    manifest = {'source_scenario':str(source),'scenario_sha256':scenario_digest(scenario),'git_revision':revision,
                'source_sha256':sources,'compiler':subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
                'flags':FLAGS,'binary_sha256':{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in binaries.items()},
                'repeats':repeats,'warmups':warmups,'max_expansions':max_expansions,'timeout_seconds_per_batch':timeout,
                'oracle':check_oracle,'complete':False}
    manifest.update({'evaluation_policy':POLICY,'received_forecasts':len(decisions),
                     'planner_queries':len(selected),'skipped_forecasts':len(decisions)-len(selected),
                     'driver_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                                      ('sipp_baseline/repair.py','sipp_baseline/runner.py','sipp_baseline/events.py','sipp_baseline/model.py','sipp_baseline/diagnostics.py')}})
    (output/'events.json').write_text(json.dumps(decisions,indent=2)+'\n')
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    reference = [oracle(scenario,f) for f in selected] if check_oracle else None
    samples = {name:[[] for _ in selected] for name in binaries}
    streams = {name:(output/f'{name}.jsonl').open('w') for name in binaries}
    try:
        for repetition in range(-warmups,repeats):
            results = {}
            # Alternate execution order to reduce systematic warm-cache bias.
            order = list(binaries) if repetition%2==0 else list(reversed(binaries))
            for name in order:
                results[name] = solve_batch(query_scenario,max_expansions=max_expansions,binary=binaries[name],timeout=timeout)
            for i,forecast in enumerate(selected):
                verdict = classify_pair(results['baseline'][i],results['incremental'][i])
                for name in binaries:
                    row = results[name][i]
                    row['path_valid'] = validate(scenario,forecast,row)
                    if reference and row['status']!='expansion_limit' and (row['status'],row['cost_ticks'])!=reference[i]:
                        raise RuntimeError(f'oracle mismatch: {name} {forecast["id"]}')
                    row.update({'forecast_id':forecast['id'],'repetition':repetition,'algorithm':name,'comparison':verdict})
                    if repetition>=0:
                        streams[name].write(json.dumps(row,sort_keys=True)+'\n');streams[name].flush()
                        samples[name][i].append(row)
                if verdict=='mismatch':
                    (output/'mismatch.json').write_text(json.dumps({'forecast_id':forecast['id'],
                        'baseline':results['baseline'][i],'incremental':results['incremental'][i]},indent=2)+'\n')
                    raise RuntimeError(f'full-replan/repair mismatch at {forecast["id"]}; see {output}/mismatch.json')
    finally:
        for stream in streams.values():
            stream.close()
    rows = []
    for i,forecast in enumerate(selected):
        base,inc = samples['baseline'][i],samples['incremental'][i]
        a,b = base[0],inc[0]
        if any((r['status'],r['cost_ticks'])!=(a['status'],a['cost_ticks']) for r in base):
            raise RuntimeError('baseline result changed across repetitions')
        if any((r['status'],r['cost_ticks'])!=(b['status'],b['cost_ticks']) for r in inc):
            raise RuntimeError('repair result changed across repetitions')
        baseline_us = statistics.median(r['total_us'] for r in base)
        incremental_us = statistics.median(r['total_us'] for r in inc)
        rows.append({'forecast_id':forecast['id'],'phase':'initial' if i==0 else 'update',
                     'verdict':classify_pair(a,b),'baseline_status':a['status'],'incremental_status':b['status'],
                     'cost_ticks':b['cost_ticks'],'baseline_us':baseline_us,'incremental_us':incremental_us,
                     'speedup':baseline_us/incremental_us if incremental_us else None,
                     'baseline_expansions':a['expansions'],'incremental_expansions':b['expansions'],
                     'baseline_projections':a['projections'],'incremental_projections':b['projections'],
                     **{key:b[key] for key in ('changed_cells','suspect_projections','changed_projections','reused_projections',
                                              'retired_labels','retired_owners','reactivated_intervals','compactions','stored_labels','stored_projections')},
                     **{key:b[key] for key in COUNTERS},
                     **{key:statistics.median(r[key] for r in inc) for key in PHASES},
                     **change_size(scenario,selected[i-1] if i else None,forecast),
                     **repair_metrics(a,b)})
        # Time fractions use the same per-query medians as the main comparison.
        rows[-1]['maintenance_time_fraction']=rows[-1]['maintenance_us']/incremental_us if incremental_us else None
    with (output/'comparison.csv').open('w',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    updates = rows[1:]
    aggregate = {'evaluation_policy':POLICY,'received_forecasts':len(decisions),
                 'skipped_forecasts':len(decisions)-len(selected),'replanning_events':len(rows)-1,
                 'queries':len(rows),'verdicts':dict(Counter(row['verdict'] for row in rows)),
                 'initial':rows[0], 'updates':{
                     'baseline_total_us':sum(r['baseline_us'] for r in updates),
                     'incremental_total_us':sum(r['incremental_us'] for r in updates),
                     'baseline_expansions':sum(r['baseline_expansions'] for r in updates),
                     'incremental_expansions':sum(r['incremental_expansions'] for r in updates)}}
    aggregate['diagnostics']=aggregate_diagnostics(updates)
    totals = aggregate['updates']
    totals['speedup'] = totals['baseline_total_us']/totals['incremental_total_us'] if totals['incremental_total_us'] else None
    (output/'summary.json').write_text(json.dumps(aggregate,indent=2)+'\n')
    manifest['complete'] = True
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return aggregate


def compare_suite(suite_directory, output, repeats=3, warmups=1, max_expansions=2_000_000, timeout=120, resume=False):
    suite_directory = Path(suite_directory).resolve()
    suite = json.loads((suite_directory/'suite.json').read_text())
    if not suite['complete']:
        raise ValueError('source q suite is incomplete')
    output = Path(output)
    config = {'source_suite':str(suite_directory),'repeats':repeats,'warmups':warmups,
              'max_expansions':max_expansions,'timeout':timeout,'evaluation_policy':POLICY}
    if output.exists():
        if not resume or json.loads((output/'suite-summary.json').read_text())['config']!=config:
            raise ValueError('output exists or comparison settings differ; use a matching --resume')
    output.mkdir(parents=True,exist_ok=resume)
    summaries = []
    def write_report(complete):
        (output/'suite-summary.json').write_text(json.dumps({'config':config,'complete':complete,'runs':summaries},indent=2)+'\n')
        lines = []
        for row in summaries:
            initial,u = row['initial'],row['updates']
            lines.append('<tr>'+''.join(f'<td>{html.escape(str(x))}</td>' for x in
                [row['map'],row['q'],row['received_forecasts'],row['skipped_forecasts'],row['replanning_events'],f"{row['verdicts'].get('matched',0)}/{row['queries']}",
                 f"{initial['incremental_us']/initial['baseline_us']:.2f}×",f"{u['baseline_total_us']/1000:.2f}",
                 f"{u['incremental_total_us']/1000:.2f}",f"{u['speedup']:.2f}×" if u['speedup'] else '— (no replans)',
                 u['baseline_expansions'],u['incremental_expansions'],
                 *('—' if row['diagnostics'][key] is None else f"{row['diagnostics'][key]:.3f}" for key in
                   ('retired_label_fraction','search_expansion_ratio','maintenance_time_fraction'))])+f'<td><a href="{row["directory"]}/comparison.csv">CSV</a></td></tr>')
        page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SIPP-IP repair comparison</title><style>body{font:15px/1.6 system-ui;background:#f3f5f5;color:#172c37;margin:30px}main{max-width:1450px;margin:auto}table{border-collapse:collapse;background:white;width:100%;font-size:13px}th,td{padding:10px;border-bottom:1px solid #d8e1e4;text-align:left}p{color:#526a75}a{color:#225ed5}.scroll{overflow:auto}</style><main><h1>Incremental repair vs full replanning</h1><p>'''+('Complete' if complete else 'In progress')+''' · Planning runs initially and only when effective reservations change. Identical snapshots are skipped for both planners; q=0 has no replans or update speedup. Costs and paths checked. Initial overhead is incremental time / baseline time. Update speedup is baseline time / incremental time; values below 1 mean repair was slower.</p><div class="scroll"><table><thead><tr><th>Map</th><th>q</th><th>Received</th><th>Skipped</th><th>Replans</th><th>Matched</th><th>Initial overhead</th><th>Full updates (ms)</th><th>Repair updates (ms)</th><th>Update speedup</th><th>Full expansions</th><th>Repair expansions</th><th>Retired label fraction</th><th>Search expansion ratio</th><th>Maintenance share</th><th>Details</th></tr></thead><tbody>'''+''.join(lines)+'''</tbody></table></div><p>A shared prediction-change filter runs before either planner and is outside the planner timings. Candidate prediction revisions may occur periodically; their arrival alone never triggers planning. Times include planner input parsing, normalization, diff, repair and search; incremental maintenance includes compaction. Retained cache disposal at process exit is outside incremental per-query time. Each repetition starts a fresh planner and replays the whole sequence. Resource-limited pairs are inconclusive, not correctness matches. These are exploratory measurements on one environment seed.</p><a href="suite-summary.json">Full summary JSON</a></main></html>'''
        (output/'index.html').write_text(page)
    write_report(False)
    for run in suite['runs']:
        relative = Path(run['forecasts'][0]['view']).parent
        source = suite_directory/relative/'scenario.json'
        destination = output/relative
        print(f"Comparing {run['map']} q={run['q']}",flush=True)
        if destination.exists():
            manifest = json.loads((destination/'manifest.json').read_text())
            if not resume or not manifest.get('complete'):
                raise ValueError(f'cannot reuse incomplete comparison: {destination}')
            if manifest.get('evaluation_policy')!=POLICY or any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=digest
                    for p,digest in manifest.get('driver_sha256',{}).items()) or not manifest.get('driver_sha256'):
                raise ValueError(f'cannot resume a different evaluation policy or driver: {destination}')
            binaries = {'baseline':ensure_built(),'incremental':ensure_incremental()}
            sources = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in manifest['source_sha256']}
            if (sources!=manifest['source_sha256'] or
                {k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in binaries.items()}!=manifest['binary_sha256'] or
                str(source.resolve())!=manifest['source_scenario'] or
                scenario_digest(load(source))!=manifest['scenario_sha256']):
                raise ValueError(f'cannot resume changed inputs or planner: {destination}; use a new output directory')
            summary = json.loads((destination/'summary.json').read_text())
        else:
            summary = compare_case(source,destination,repeats,warmups,max_expansions,timeout)
        summaries.append({**summary,'map':run['map'],'q':run['q'],'directory':relative.as_posix()})
        write_report(False)
    write_report(True)
    return (output/'index.html').resolve()
