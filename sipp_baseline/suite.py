"""Matched multi-map q sweeps, measurements, and an offline comparison viewer."""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

from .generate import generate
from .events import POLICY
from .model import read_map
from .paper import MAPS
from .runner import ROOT, benchmark, summarize
from .visualize import export_viewer

DEFAULT_Q = (0,.1,.25,.5,1)


def initial_hash(scenario):
    return hashlib.sha256(json.dumps(scenario['forecasts'][0],sort_keys=True,separators=(',',':')).encode()).hexdigest()


def changed_cells(before, after):
    def index(rows):
        cells = {}
        for r,c,a,b in rows:
            cells.setdefault((r,c),[]).append((a,b))
        return cells
    a,b = index(before),index(after)
    return sum(a.get(cell)!=b.get(cell) for cell in a.keys()|b.keys())


def collect_run(scenario, directory, relative):
    summary = summarize(directory/'results.jsonl')
    metrics = {row['forecast_id']:row for row in summary}
    forecasts = []
    previous = scenario['forecasts'][0]
    split = (directory/'viewer-instance-01.html').exists() and 'replay-data' not in (directory/'viewer.html').read_text()
    for i,f in enumerate(scenario['forecasts']):
        result = metrics[f['id']]
        outcomes = Counter(event['outcome'] for event in f['events'])
        forecasts.append({**result,'revision_tick':f['revision_tick'],
                          'proposed':len(f['events']),'applied':outcomes.get('applied',0),
                          'outcomes':dict(outcomes),
                          'changed_obstacles':sum(a!=b for a,b in zip(previous['obstacles'],f['obstacles'])),
                          'changed_cells':changed_cells(previous['reservations'],f['reservations']),
                          'view':f'{relative}/viewer-instance-{i+1:02}.html' if split else f'{relative}/viewer.html',
                          'view_forecast':0 if split else i})
        previous = f
    return {'map':scenario['metadata']['map_name'],'q':scenario['metadata']['change_probability'],
            'density':scenario['metadata']['obstacle_density'],'obstacles':scenario['metadata']['obstacles'],
            'initial_sha256':initial_hash(scenario),'forecasts':forecasts,
            'median_update_ms':statistics.median(row['median_total_us']/1000 for row in forecasts[1:] if row['planner_invoked'])
                if any(row['planner_invoked'] for row in forecasts[1:]) else None}


def write_suite(output, config, runs, complete):
    payload = {'config':config,'runs':runs,'complete':complete}
    (output/'suite.json').write_text(json.dumps(payload,indent=2)+'\n')
    records = []
    for run in runs:
        for i,f in enumerate(run['forecasts']):
            records.append({'map':run['map'],'seed':config['seed'],'q':run['q'],'density_p':run['density'],
                            'obstacles':run['obstacles'],'forecast':i,'revision_tick':f['revision_tick'],
                            'status':f['status'],'cost_ticks':f['cost_ticks'],
                            'planner_invoked':f['planner_invoked'],
                            'median_total_ms':f['median_total_us']/1000,'expansions':f['expansions'],
                            'proposed':f['proposed'],'applied':f['applied'],
                            'changed_obstacles':f['changed_obstacles'],'changed_cells':f['changed_cells']})
    if records:
        with (output/'comparison.csv').open('w',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=list(records[0]))
            writer.writeheader();writer.writerows(records)
    encoded = json.dumps(payload,separators=(',',':'),ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template = Path(__file__).with_name('comparison.html').read_text()
    (output/'index.html').write_text(template.replace('__COMPARISON_DATA__',encoded))


def build_suite(output, maps=MAPS, q_values=DEFAULT_Q, seed=7, density=.04,
                updates=5, update_interval=100, horizon=40000, repeats=3, warmups=1,
                max_expansions=2_000_000, timeout=120, generation_timeout=120, resume=False):
    output = Path(output)
    if not maps or any(name not in MAPS for name in maps) or len(set(maps))!=len(maps):
        raise ValueError('choose unique supported map names')
    if not q_values or len(set(q_values))!=len(q_values) or any(not math.isfinite(q) or not 0<=q<=1 for q in q_values):
        raise ValueError('q values must be unique probabilities in [0,1]')
    config = {'maps':list(maps),'q_values':list(q_values),'seed':seed,'density':density,
              'updates':updates,'update_interval':update_interval,'horizon':horizon,
              'repeats':repeats,'warmups':warmups,'max_expansions':max_expansions,'timeout':timeout,
              'generation_timeout':generation_timeout,'generator':'sipp-ip-upstream-v2','evaluation_policy':POLICY}
    if output.exists():
        if not resume:
            raise ValueError(f'output already exists: {output}; use --resume for matching completed runs')
        saved = json.loads((output/'suite.json').read_text())
        if saved['config'] != config:
            raise ValueError('existing suite settings do not match the requested sweep')
    output.mkdir(parents=True,exist_ok=resume)
    runs = []
    write_suite(output,config,runs,False)
    for name in maps:
        print(f'Generating common initial obstacles: {name}',flush=True)
        grid = read_map(ROOT/'maps'/f'{name}.txt')
        common = dict(seed=seed,density=density,updates=updates,update_interval=update_interval,
                      horizon=horizon,map_name=name,generation_timeout=generation_timeout)
        zero = generate(grid,change_probability=0,**common)
        digest = initial_hash(zero)
        base = {key:zero['forecasts'][0][key] for key in ('obstacles','reservations')}
        if horizon!=40000:
            # Capture full reservations for the upstream equality assertion.
            from .generate import SOURCE_HORIZON, canonical, obstacle_reservations
            base['reservations'] = canonical([row for o in base['obstacles'] for row in obstacle_reservations(o,SOURCE_HORIZON)],SOURCE_HORIZON)
        for q in q_values:
            token = format(q,'.12g').replace('.','_')
            relative = f'{name}/q-{token}'
            directory = output/relative
            print(f'  {name}: q={q:g}',flush=True)
            if directory.exists():
                manifest = json.loads((directory/'manifest.json').read_text())
                if not resume or not manifest.get('complete'):
                    raise ValueError(f'incomplete run cannot be reused: {directory}')
                if manifest.get('evaluation_policy')!=POLICY:
                    raise ValueError(f'cached run uses a different evaluation policy: {directory}')
                scenario = json.loads((directory/'scenario.json').read_text())
                if (initial_hash(scenario)!=digest or scenario['metadata']['change_probability']!=q
                        or manifest['repeats']!=repeats or manifest['warmups']!=warmups
                        or manifest['max_expansions']!=max_expansions):
                    raise ValueError(f'cached run settings or initial obstacles differ: {directory}')
            else:
                scenario = zero if q==0 else generate(grid,change_probability=q,_base=base,**common)
                if initial_hash(scenario)!=digest:
                    raise RuntimeError('q sweep initial forecasts differ')
                benchmark(scenario,directory,repeats=repeats,warmups=warmups,
                          max_expansions=max_expansions,timeout=timeout)
            export_viewer(directory,force=resume)
            runs.append(collect_run(scenario,directory,relative))
            write_suite(output,config,runs,False)
    write_suite(output,config,runs,True)
    return (output/'index.html').resolve()
