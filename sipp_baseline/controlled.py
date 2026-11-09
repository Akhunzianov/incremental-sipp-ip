"""Isolated causal one-obstacle experiments on unchanged upstream initial worlds."""
from collections import defaultdict
import copy
import csv
import hashlib
import html
import json
from pathlib import Path
import random

from .diagnostics import change_size
from .generate import canonical, generate, obstacle_reservations
from .model import check_scenario, read_map
from .paper import MAPS
from .repair import compare_case, scenario_digest
from .runner import ROOT

MODES = ('pause-10','accelerate-one-edge','decelerate-one-edge','nearby-waypoint')


def mutate(obstacle,index,mode,waypoint=None):
    """Exactly one intervention; all subsequent times shift, all extras stay fixed."""
    result=copy.deepcopy(obstacle);nodes=result['nodes'];u,v=nodes[index:index+2]
    duration=v[2]-u[2]
    if u[:2]==v[:2] or not 20<=duration<=90:
        raise ValueError('choose a moving edge with room to increase/decrease its duration')
    if mode=='pause-10':
        result['nodes']=nodes[:index+1]+[[*u[:2],u[2]+10]]+[[r,c,t+10] for r,c,t in nodes[index+1:]]
    elif mode in ('accelerate-one-edge','decelerate-one-edge'):
        delta=-10 if mode=='accelerate-one-edge' else 10
        result['nodes']=nodes[:index+1]+[[r,c,t+delta] for r,c,t in nodes[index+1:]]
    elif mode=='nearby-waypoint':
        if waypoint is None:raise ValueError('a nearby waypoint is required')
        result['nodes']=nodes[:index+1]+[[*waypoint,v[2]]]+[[r,c,t+duration] for r,c,t in nodes[index+1:]]
    else:raise ValueError('unsupported controlled mode')
    return result


def controlled_cases(base,revision_tick=100):
    """Select by geometry/occupancy only, never by planner timings or path cost.

    Return four paired variants sharing one obstacle/boundary, or report that no
    such set is available. Goal/start and in-flight edges are preserved.
    """
    if not 0<=revision_tick<base['horizon']:raise ValueError('revision must precede horizon')
    initial=base['forecasts'][0];obstacles=initial.get('obstacles',[])
    horizon=base['horizon'];grid=base['grid']
    forbidden={tuple(base['start'][:2]),tuple(base['goal'][:2])}
    per_obstacle={o['id']:obstacle_reservations(o,horizon) for o in obstacles}
    occupancy=defaultdict(list)
    prioritized=base['metadata']['obstacle_interaction_policy']=='prioritized'
    if prioritized:
        for oid,rows in per_obstacle.items():
            for r,c,a,b in rows:occupancy[r,c].append((oid,a,b))
    ids=list(range(len(obstacles)))
    rng=random.Random(int.from_bytes(hashlib.sha256(f"{base['metadata']['seed']}:{base['metadata']['map_name']}:controlled".encode()).digest(),'big'))
    rng.shuffle(ids)
    for idx in ids:
        obstacle=obstacles[idx];nodes=obstacle['nodes']
        # Use the first eligible future moving edge per obstacle. This rule does
        # not depend on the robot's planned path or on which planner is faster.
        edge=next((i for i,(a,b) in enumerate(zip(nodes,nodes[1:]))
                   if a[2]>revision_tick and a[:2]!=b[:2] and 20<=b[2]-a[2]<=90),None)
        if edge is None:continue
        u,v=nodes[edge:edge+2];r,c=u[:2]
        neighbors=sorted((r+dr,c+dc) for dr in (-1,0,1) for dc in (-1,0,1)
                         if (dr or dc) and 0<=r+dr<len(grid) and 0<=c+dc<len(grid[0])
                         and grid[r+dr][c+dc]=='.' and (r+dr,c+dc) not in forbidden
                         and [r+dr,c+dc]!=v[:2] and max(abs(r+dr-v[0]),abs(c+dc-v[1]))==1)
        others=[row for o in obstacles if o['id']!=obstacle['id'] for row in per_obstacle[o['id']]]
        variants=[]
        for mode in MODES:
            accepted=None
            for waypoint in neighbors if mode=='nearby-waypoint' else [None]:
                changed=mutate(obstacle,edge,mode,waypoint)
                if changed['nodes'][-1][2]>horizon:continue
                rows=obstacle_reservations(changed,horizon)
                if prioritized and any(max(a,u[2])<=end and start<=b
                      for rr,cc,a,b in rows if b>=u[2]
                      for oid,start,end in occupancy[rr,cc] if oid!=obstacle['id']):continue
                reservations=canonical(others+rows,horizon)
                after={'id':'changed','revision_tick':revision_tick,'reservations':reservations}
                size=change_size(base,initial,after)
                if not size['reservation_changed_cells']:continue
                if size['change_first_tick']<=revision_tick:
                    raise RuntimeError('controlled change modified the observed prefix')
                event={'obstacle':obstacle['id'],'mode':mode,'revision_tick':revision_tick,
                       'effective_tick':u[2],'edge_index':edge,'outcome':'applied',
                       'original_edge_ticks':v[2]-u[2],**({'waypoint':list(waypoint)} if waypoint else {})}
                after['events']=[event]
                data={key:copy.deepcopy(base[key]) for key in ('schema_version','tick_seconds','horizon','grid','start','goal')}
                data['start_tick']=base.get('start_tick',0)
                data['forecasts']=[{'id':'initial','revision_tick':0,'events':[],
                                    'reservations':initial['reservations']},after]
                data['metadata']={**base['metadata'],'experiment':'one-obstacle-v1','controlled_mode':mode,
                                  'changed_obstacles':1,'controlled_event':event,
                                  'changed_obstacle_before':copy.deepcopy(obstacle),
                                  'changed_obstacle_after':changed}
                for key in ('change_probability','change_probability_symbol','change_probability_unit'):
                    data['metadata'].pop(key,None)
                accepted=check_scenario(data);break
            if accepted is None:break
            variants.append(accepted)
        if len(variants)==len(MODES):return variants
    return []


def run_controlled(output,maps=MAPS,seeds=(7,11,19),density=.04,revision_tick=100,
                   repeats=3,warmups=1,max_expansions=2_000_000,timeout=180):
    if not maps or len(set(maps))!=len(maps) or any(m not in MAPS for m in maps):
        raise ValueError('choose unique supported maps')
    if not seeds or len(set(seeds))!=len(seeds):raise ValueError('choose unique seeds')
    output=Path(output)
    if output.exists():raise ValueError('output exists; choose a new experiment directory')
    output.mkdir(parents=True)
    config={'maps':list(maps),'seeds':list(seeds),'density':density,'revision_tick':revision_tick,
            'repeats':repeats,'warmups':warmups,'max_expansions':max_expansions,'timeout':timeout,
            'modes':list(MODES),'selection':'first feasible common obstacle/boundary, independent of planner performance',
            'generator_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                                ('sipp_baseline/controlled.py','sipp_baseline/generate.py','sipp_baseline/upstream_generator.py')}}
    runs=[];unavailable=[]
    def save(complete):
        (output/'controlled-suite.json').write_text(json.dumps({'config':config,'runs':runs,'unavailable':unavailable,'complete':complete},indent=2)+'\n')
    save(False)
    for name in maps:
        grid=read_map(ROOT/'maps'/f'{name}.txt')
        for seed in seeds:
            print(f'Controlled experiments: {name} seed={seed}',flush=True)
            base=generate(grid,seed=seed,updates=0,density=density,change_probability=0,map_name=name)
            directory=output/name/f'seed-{seed}';directory.mkdir(parents=True)
            base_path=directory/'base.json';base_path.write_text(json.dumps(base,separators=(',',':'))+'\n')
            base_digest=scenario_digest(base)
            variants=controlled_cases(base,revision_tick)
            if not variants:
                unavailable.append({'map':name,'seed':seed,'reason':'no common feasible nonempty four-mode intervention'})
                save(False);continue
            for data in variants:
                mode=data['metadata']['controlled_mode'];case=directory/mode;case.mkdir()
                data['metadata'].update({'base_scenario':str(base_path.resolve()),'base_sha256':base_digest})
                source=case/'scenario.json';source.write_text(json.dumps(data,separators=(',',':'))+'\n')
                summary=compare_case(source,case/'comparison',repeats,warmups,max_expansions,timeout)
                row={'map':name,'seed':seed,'mode':mode,'directory':case.relative_to(output).as_posix(),
                     'obstacle':data['metadata']['controlled_event']['obstacle'],
                     'effective_tick':data['metadata']['controlled_event']['effective_tick'],**summary}
                runs.append(row);save(False)
    save(True)
    render_controlled(output)
    return (output/'index.html').resolve()


def render_controlled(output):
    output=Path(output);suite=json.loads((output/'controlled-suite.json').read_text());rows=[]
    for run in suite['runs']:
        with (output/run['directory']/'comparison/comparison.csv').open() as stream:
            change=list(csv.DictReader(stream))[-1]
        rows.append({'map':run['map'],'seed':run['seed'],'mode':run['mode'],'obstacle':run['obstacle'],
                     'effective_tick':run['effective_tick'],'directory':run['directory'],**change})
    if rows:
        with (output/'diagnostics.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    def fmt(x):return '—' if x in (None,'','None') else f'{float(x):.3f}'
    body=[]
    for r in rows:
        values=[r['map'],r['seed'],r['mode'],r['obstacle'],r['verdict'],fmt(r['speedup']),
                r['reservation_changed_cells'],fmt(r['suspect_projection_fraction']),
                fmt(r['retired_label_fraction']),fmt(r['retained_coverage_fraction']),
                fmt(r['cascade_amplification']),fmt(r['search_expansion_ratio']),fmt(r['maintenance_time_fraction'])]
        body.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in values)+
                    f'<td><a href="{html.escape(r["directory"],quote=True)}/comparison/comparison.csv">CSV</a></td></tr>')
    page='''<!doctype html><meta charset="utf-8"><title>Controlled repair diagnostics</title><style>body{font:14px system-ui;margin:30px;color:#18313e}table{border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}.scroll{overflow:auto}p{max-width:1000px;line-height:1.6}</style><h1>One-obstacle repair diagnostics</h1><p>Each four-mode group shares an upstream initial world, one changed obstacle and one future boundary. The other obstacles remain unchanged. Both planners run only on actual prediction changes. Speedup is full replan / repair; above 1 is faster repair. Fractions are 0–1; expansion ratio is repair / full search. Cascade amplification is retired labels / directly invalidated labels. Selection uses feasibility, never planner performance. Resource-limited pairs are inconclusive. Times are exploratory, with initialization separate.</p><div class="scroll"><table><thead><tr>'''
    page+=''.join('<th>'+x+'</th>' for x in ['Map','Seed','Change','Obstacle','Verdict','Speedup','Changed cells','Suspect fraction','Retired labels fraction','Retained coverage','Cascade amplification','Search ratio','Maintenance share','Details'])
    page+='</tr></thead><tbody>'+''.join(body)+'</tbody></table></div><p>'+str(len(suite['unavailable']))+' unavailable groups are recorded in <a href="controlled-suite.json">the complete suite JSON</a>. <a href="diagnostics.csv">All diagnostics CSV</a>. Full trajectories and phase timings are in each case directory.</p>'
    (output/'index.html').write_text(page)
