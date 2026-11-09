"""Build, audit and evaluate the broader scenario coverage suite."""
from collections import Counter
import csv
import gzip
import hashlib
import html
import json
from pathlib import Path
import subprocess

from .diagnostics import change_size
from .generate import generate, obstacle_reservations
from .model import load, read_map
from .obstacle_routes import StaticRoutes
from .paper import MAPS
from .repair import compare_case, ensure_incremental, scenario_digest
from .runner import ROOT, ensure_built, solve_batch
from .scenario_cases import PROFILES, build_profile, engineered_cases, reservations
from .validation import validate

VERSION='diverse-scenarios-v1'


def _collision_windows(plans,horizon,since=0):
    cells={};windows={}
    for oid,o in plans.items():
        for r,c,a,b in obstacle_reservations(o,horizon):cells.setdefault((r,c),[]).append((a,b,oid))
    for cell,intervals in cells.items():
        active=[]
        for a,b,oid in sorted(intervals):
            active=[(end,other) for end,other in active if end>=a]
            for end,other in active:
                lo,hi=max(a,since),min(b,end)
                if other!=oid and lo<=hi:
                    key=(*cell,*sorted((oid,other)));windows.setdefault(key,[]).append((lo,hi))
            active.append((b,oid))
    for key,intervals in windows.items():
        merged=[]
        for a,b in sorted(intervals):
            if merged and a<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:merged.append((a,b))
        windows[key]=merged
    return windows


def _outside_windows(intervals,allowed):
    for lo,hi in intervals:
        point=lo
        for a,b in allowed:
            if b<point:continue
            if a>point:return True
            point=max(point,b+1)
            if point>hi:break
        if point<=hi:return True
    return False


def write_json(path,value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)


def audit_trace(data,initial,trace,prioritized=False):
    plans={o['id']:o for o in initial};horizon=data['horizon']
    inherited=_collision_windows(plans,horizon) if prioritized else {}
    if reservations(list(plans.values()),horizon)!=data['forecasts'][0]['reservations']:
        raise ValueError('initial obstacle plans do not reconstruct reservations')
    for forecast,entry in zip(data['forecasts'][1:],trace):
        if forecast['id']!=entry['forecast_id']:raise ValueError('trace forecast mismatch')
        ids=[]
        for change in entry['changes']:
            oid=change['obstacle'];before=change['before'];after=change['after'];ids.append(oid)
            if plans[oid]!=before or before==after or before['id']!=oid or after['id']!=oid:raise ValueError('invalid trajectory delta')
            if before['extra_reservations']!=after['extra_reservations']:raise ValueError('changed source extras')
            if before.get('start',before['nodes'][0][:2])!=after.get('start',after['nodes'][0][:2]) or before['goal']!=after['goal'] or before['nodes'][0]!=after['nodes'][0]:
                raise ValueError('changed obstacle start/goal')
            # Full source trajectories may extend beyond the planning horizon;
            # reservation reconstruction clips them, as in the upstream loader.
            if after['nodes'][-1][:2]!=after['goal']:
                raise ValueError('invalid obstacle endpoint')
            for a,b in zip(after['nodes'],after['nodes'][1:]):
                step=max(abs(a[0]-b[0]),abs(a[1]-b[1]));dt=b[2]-a[2]
                if step>1 or dt<=0 or (step and not 10<=dt<=100):raise ValueError('illegal obstacle step')
                if not (0<=b[0]<len(data['grid']) and 0<=b[1]<len(data['grid'][0])) or data['grid'][b[0]][b[1]]!='.':
                    raise ValueError('obstacle enters a wall')
            size=change_size(data,{'reservations':obstacle_reservations(before,horizon)},
                                  {'reservations':obstacle_reservations(after,horizon)})
            if size['change_first_tick'] is not None and size['change_first_tick']<=entry['revision_tick']:
                raise ValueError('obstacle changed the observed prefix')
            plans[oid]=after
        if len(ids)!=len(set(ids)) or set(ids)!=set(forecast['changed_ids']):raise ValueError('changed IDs mismatch')
        if reservations(list(plans.values()),horizon)!=forecast['reservations']:raise ValueError('trace does not reconstruct prediction')
        if prioritized:
            for key,intervals in _collision_windows(plans,horizon,entry['revision_tick']).items():
                if _outside_windows(intervals,inherited.get(key,[])):
                    raise ValueError('new prioritized obstacle conflict')
    if len(trace)!=len(data['forecasts'])-1:raise ValueError('trace length mismatch')
    return {'inherited_conflict_cell_pairs':len(inherited) if prioritized else None,
            'inherited_conflict_pair_ticks':sum(b-a+1 for xs in inherited.values() for a,b in xs) if prioritized else None}


def save_case(root,relative,data,initial,trace,info):
    directory=root/relative;directory.mkdir(parents=True)
    audit=audit_trace(data,initial,trace,info['tier']=='engineered' or data['metadata']['obstacle_interaction_policy']=='prioritized')
    payload=gzip.compress(json.dumps(trace,separators=(',',':')).encode(),mtime=0)
    (directory/'trajectory-changes.json.gz').write_bytes(payload)
    data['metadata'].update({'trajectory_trace':'trajectory-changes.json.gz',
                            'trajectory_trace_sha256':hashlib.sha256(payload).hexdigest(),'suite_version':VERSION,
                            'trajectory_audit':audit})
    (directory/'scenario.json').write_text(json.dumps(data,separators=(',',':'))+'\n')
    return {**info,**audit,'directory':relative,'scenario_sha256':scenario_digest(data),
            'received_forecasts':len(data['forecasts']),
            'changed_counts':[f['changed_obstacles'] for f in data['forecasts'][1:]]}


def build_scenarios(output,maps=MAPS,seeds=(7,11,19),densities=(.02,.04),include_engineered=True,cache=None):
    if not maps or len(set(maps))!=len(maps) or any(m not in MAPS for m in maps):raise ValueError('choose unique supported maps')
    if not seeds or len(set(seeds))!=len(seeds):raise ValueError('choose unique seeds')
    if not densities or len(set(densities))!=len(densities) or any(not 0<p<=1 for p in densities):raise ValueError('choose unique densities in (0,1]')
    output=Path(output)
    if output.exists():raise ValueError('output exists; choose a new scenario directory')
    output.mkdir(parents=True);cases=[]
    config={'version':VERSION,'maps':list(maps),'seeds':list(seeds),'densities':list(densities),
            'base_cache':str(Path(cache).resolve()) if cache else None,
            'profiles':[list(p) for p in PROFILES],'include_engineered':include_engineered,
            'generator_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
             ('sipp_baseline/scenario_cases.py','sipp_baseline/scenario_suite.py','sipp_baseline/generate.py',
              'sipp_baseline/upstream_generator.py','sipp_baseline/obstacle_routes.py','src/obstacle_generator.cpp')}}
    def save(complete):write_json(output/'suite.json',{'config':config,'cases':cases,'complete':complete})
    save(False)
    for name in maps:
        grid=read_map(ROOT/'maps'/f'{name}.txt')
        for seed in seeds:
            for density in densities:
                print(f'Generating scenarios: {name} seed={seed} p={density}',flush=True)
                candidate=Path(cache)/name/f'seed-{seed}/base.json' if cache else None
                base=load(candidate) if candidate and candidate.exists() else None
                if base is None or base['metadata']['requested_density']!=density or base['metadata']['seed']!=seed or base['metadata']['map_name']!=name or base['grid']!=grid or base['horizon']!=40000:
                    base=generate(grid,seed=seed,updates=0,change_probability=0,density=density,map_name=name)
                base_digest=scenario_digest(base)
                token=format(density,'.6g').replace('.','_');world=f'{name}/seed-{seed}/p-{token}'
                folder=output/world;folder.mkdir(parents=True)
                (folder/'base.json').write_text(json.dumps(base,separators=(',',':'))+'\n')
                reference=solve_batch(base,forecasts=base['forecasts'][:1],max_expansions=1_000_000)[0]
                validate(base,base['forecasts'][0],reference);write_json(folder/'reference.json',reference)
                forbidden={tuple(base['start'][:2]),tuple(base['goal'][:2])}
                with StaticRoutes(grid,forbidden) as router:
                    for spec in PROFILES:
                        data,trace=build_profile(base,spec,reference,router.via)
                        data['metadata'].update({'base_scenario':'../base.json','base_sha256':base_digest,
                                                 'reference_status':reference['status'],'reference_cost':reference['cost_ticks']})
                        cases.append(save_case(output,f'{world}/{spec[0]}',data,base['forecasts'][0]['obstacles'],trace,
                            {'tier':'upstream','map':name,'seed':seed,'density':density,'profile':spec[0],
                             'number_level':spec[1],'spatial_pattern':spec[2],'time_pattern':spec[3],
                             'history_pattern':spec[4],'total_obstacles':len(base['forecasts'][0]['obstacles'])}))
                        save(False)
    if include_engineered:
        for seed in seeds:
            for count in (2,4):
                for data,initial,trace in engineered_cases(seed,count):
                    family=data['metadata']['profile'];relative=f'engineered/seed-{seed}/agents-{count}/{family}'
                    data['metadata']['initial_obstacles']=initial
                    cases.append(save_case(output,relative,data,initial,trace,
                        {'tier':'engineered','map':'engineered-'+family,'seed':seed,'density':data['metadata']['obstacle_density'],
                         'profile':family,'total_obstacles':count}))
                    save(False)
    save(True)
    return (output/'suite.json').resolve()


def classify_transition(data,forecast,old,new,invoked=True):
    if not invoked:return {'outcome':'skipped_unchanged','old_path_valid':None,'cost_delta':None}
    if 'expansion_limit' in (old['status'],new['status']):return {'outcome':'inconclusive','old_path_valid':None,'cost_delta':None}
    valid=None
    if old['status']=='solved':
        try:validate(data,forecast,old);valid=True
        except ValueError:valid=False
    if valid and new['status']!='solved':raise RuntimeError('a feasible old path contradicts claimed infeasibility')
    if new['status']!='solved':outcome='no_path' if old['status']=='solved' else 'no_path_persists'
    elif old['status']!='solved':outcome='recovery'
    elif new['cost_ticks']<old['cost_ticks']:outcome='shorter_path'
    elif not valid:outcome='old_path_invalid'
    else:
        if new['cost_ticks']!=old['cost_ticks']:raise RuntimeError('a feasible old path beats the claimed optimum')
        outcome='old_path_stays_optimal'
    delta=new['cost_ticks']-old['cost_ticks'] if old['status']==new['status']=='solved' else None
    return {'outcome':outcome,'old_path_valid':valid,'cost_delta':delta}


def observed_events(source,comparison):
    data=load(source);decisions=json.loads((comparison/'events.json').read_text())
    measured={}
    with (comparison/'baseline.jsonl').open() as stream:
        for line in stream:
            row=json.loads(line)
            if row['repetition']==0:measured[row['forecast_id']]=row
    old=measured[data['forecasts'][0]['id']];previous=data['forecasts'][0];events=[]
    for forecast,decision in zip(data['forecasts'][1:],decisions[1:]):
        new=measured[decision['source_forecast_id']]
        result=classify_transition(data,forecast,old,new,decision['planner_invoked'])
        size=change_size(data,previous,forecast)
        events.append({'forecast_id':forecast['id'],'revision_tick':forecast['revision_tick'],
            'planner_invoked':decision['planner_invoked'],'changed_obstacles':forecast['changed_obstacles'],
            'changed_ids':forecast['changed_ids'],'requested_changes':forecast.get('requested_changes'),
            'eligible_obstacles':forecast.get('eligible_obstacles'),
            'proposal_outcomes':dict(Counter(e['outcome'] for e in forecast['events'])),
            'applied_modes':dict(Counter(e['mode'] for e in forecast['events'] if e['outcome']=='applied')),
            **result,**size,'change_after_old_arrival':size['change_first_tick']>old['cost_ticks']
                if size['change_first_tick'] is not None and old['status']=='solved' else None,
            'old_cost':old['cost_ticks'],'new_cost':new['cost_ticks']})
        old=new;previous=forecast
    if data['metadata']['suite_family']=='engineered':
        expected={'benign':['old_path_stays_optimal'],'shortcut-opens':['shorter_path'],
            'forced-delay':['old_path_invalid'],'forced-detour':['old_path_invalid'],
            'no-path-recovery':['no_path','recovery'],
            'alternating-recovery':['no_path','recovery','no_path','recovery']}[data['metadata']['profile']]
        for event,wanted in zip(events,expected):
            event['expected_outcome']=wanted
            if event['outcome']!='inconclusive' and event['outcome']!=wanted:
                raise RuntimeError('engineered outcome coverage failed')
    return events


def compare_scenarios(source,output,repeats=1,warmups=0,max_expansions=1_000_000,timeout=180,
                      seeds=None,densities=None,resume=False):
    source=Path(source).resolve();suite=json.loads((source/'suite.json').read_text())
    if not suite['complete']:raise ValueError('scenario suite is incomplete')
    output=Path(output)
    config={'source':str(source),'suite_sha256':hashlib.sha256((source/'suite.json').read_bytes()).hexdigest(),
            'repeats':repeats,'warmups':warmups,'max_expansions':max_expansions,'timeout':timeout,
            'seeds':list(seeds) if seeds is not None else None,'densities':list(densities) if densities is not None else None,
            'runner_sha256':hashlib.sha256((ROOT/'sipp_baseline/scenario_suite.py').read_bytes()).hexdigest()}
    if output.exists():
        if not resume or json.loads((output/'suite-summary.json').read_text())['config']!=config:
            raise ValueError('output exists or evaluation settings changed')
    output.mkdir(parents=True,exist_ok=resume);runs=[];failures=[]
    def save(complete):
        write_json(output/'suite-summary.json',{'config':config,'runs':runs,'failures':failures,'complete':complete})
    save(False)
    for case in suite['cases']:
        if seeds is not None and case['seed'] not in seeds:continue
        if densities is not None and case['tier']=='upstream' and case['density'] not in densities:continue
        print(f"Comparing {case['directory']}",flush=True)
        scenario=source/case['directory']/'scenario.json';destination=output/case['directory']
        if destination.exists():
            manifest=json.loads((destination/'manifest.json').read_text())
            binaries={'baseline':ensure_built(),'incremental':ensure_incremental()}
            if (not resume or not manifest['complete'] or scenario_digest(load(scenario))!=manifest['scenario_sha256'] or
                any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=d for kind in ('source_sha256','driver_sha256') for p,d in manifest[kind].items()) or
                any(hashlib.sha256(b.read_bytes()).hexdigest()!=manifest['binary_sha256'][k] for k,b in binaries.items())):
                raise ValueError('cannot reuse stale or incomplete case')
            summary=json.loads((destination/'summary.json').read_text())
        else:
            try:summary=compare_case(scenario,destination,repeats,warmups,max_expansions,timeout,case['tier']=='engineered')
            except subprocess.TimeoutExpired:
                failures.append({**case,'reason':'timeout','inconclusive':True});save(False);continue
        events=observed_events(scenario,destination)
        write_json(destination/'observed-events.json',events)
        runs.append({**case,'summary':summary,'events':events});save(False)
    save(True);render_scenarios(output)
    return (output/'index.html').resolve()


def render_scenarios(output):
    output=Path(output);s=json.loads((output/'suite-summary.json').read_text());events=[];body=[]
    outcomes=Counter();changed=Counter();verdicts=Counter();modes=Counter();timing=Counter()
    multi=all_obstacles=all_eligible=0
    for run in s['runs']:
        summary=run['summary'];verdicts.update(summary['verdicts'])
        counts=[e['changed_obstacles'] for e in run['events'] if e['planner_invoked']]
        speed=summary['updates']['speedup'] if summary['verdicts'].get('matched',0)==summary['queries'] else None
        for e in run['events']:
            events.append({k:run[k] for k in ('tier','map','seed','density','profile','directory')}|e)
            outcomes[e['outcome']]+=1
            if e['planner_invoked']:
                n=e['changed_obstacles'];changed['1' if n==1 else '2-4' if n<=4 else '5-25' if n<=25 else '26+']+=1
                multi+=n>=2;all_obstacles+=n>0 and n==run.get('total_obstacles')
                all_eligible+=n>0 and n==e.get('eligible_obstacles')
                modes.update(e['applied_modes'])
                timing['after_old_arrival' if e['change_after_old_arrival'] is True else
                       'before_or_at_old_arrival' if e['change_after_old_arrival'] is False else 'unknown']+=1
        values=[run['tier'],run['map'],run['seed'],run['density'],run['profile'],summary['replanning_events'],
                f'{min(counts)}–{max(counts)}' if counts else '—',
                ', '.join(sorted({e['outcome'] for e in run['events']})),
                f'{speed:.2f}x' if speed is not None else '—',f"{summary['verdicts'].get('matched',0)}/{summary['queries']}"]
        body.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in values)+
                    f'<td><a href="{html.escape(run["directory"],quote=True)}/comparison.csv">CSV</a></td></tr>')
    coverage={'cases':len(s['runs']),'failures':len(s['failures']),'verdicts':dict(verdicts),
        'observed_outcomes':dict(outcomes),'actual_changed_obstacle_bins':dict(changed),
        'multi_obstacle_replanning_events':multi,'all_obstacles_changed_events':all_obstacles,
        'all_eligible_changed_events':all_eligible,'applied_modes':dict(modes),'actual_timing':dict(timing),
        'tiers':dict(Counter(r['tier'] for r in s['runs']))}
    write_json(output/'coverage.json',coverage)
    if events:
        with (output/'events.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(dict.fromkeys(k for e in events for k in e)))
            writer.writeheader()
            writer.writerows({k:json.dumps(v,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in e.items()} for e in events)
    text='''<!doctype html><meta charset="utf-8"><title>Diverse scenario coverage</title><style>body{font:14px/1.5 system-ui;margin:30px;color:#18313e}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse}.scroll{overflow:auto}p{max-width:1100px}</style><h1>Diverse prediction-change scenarios</h1><p>Upstream-derived worlds and engineered adversarial cases are separate tiers. Only effective prediction changes trigger planning. Requested batches may be reduced by inactivity or collision rejection; the counts below are actual changed plans. Cluster/spread refers to obstacle positions at the intervention boundary, not necessarily the spatial extent of their entire changed future paths. Outcomes are measured, not inferred from q. Speedup is full replan / repair; initial plans are excluded. Capped or failed cases are inconclusive and have no speedup claim.</p>'''
    text+='<pre>'+html.escape(json.dumps(coverage,indent=2))+'</pre>'
    text+=f'<p>{s["config"]["repeats"]} measured repetition(s), {s["config"]["warmups"]} warm-up(s). One-repetition coverage runs are correctness/stress checks, not reliable performance rankings. <a href="events.csv">Observed events CSV</a> · <a href="suite-summary.json">Full summary</a></p>'
    text+='<div class="scroll"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in ['Tier','Map','Seed','Density p','Profile','Replans','Changed obstacles','Observed outcomes','Update speedup','Matched','Details'])+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'
    text+='<p>Native timings exclude shared event selection, serialization, validation, process startup and final retained-cache disposal. No single pooled speedup is reported across engineered and upstream tiers. The profile matrix provides coverage; it is not a full factorial design.</p>'
    (output/'index.html').write_text(text)
