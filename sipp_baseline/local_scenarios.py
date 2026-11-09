"""Spatially and temporally bounded changes, paired cluster/spread controls."""
from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path
import shutil

from .diagnostics import change_size
from .events import effective_reservations
from .generate import obstacle_reservations
from .model import check_scenario,load
from .repair import scenario_digest
from .runner import ROOT
from .scenario_cases import rng_for,select_obstacles,reservations
from .scenario_suite import save_case,write_json


def subtract_intervals(xs,ys):
    result=[]
    for lo,hi in xs:
        for a,b in ys:
            if b<lo:continue
            if a>hi:break
            if a>lo:result.append((lo,a-1))
            lo=max(lo,b+1)
            if lo>hi:break
        if lo<=hi:result.append((lo,hi))
    return result


def mutate_local(obstacle,index,waypoint=None):
    result=copy.deepcopy(obstacle);nodes=result['nodes'];a,b=nodes[index:index+2]
    if a[:2]==b[:2] or not 20<=b[2]-a[2]<=100:raise ValueError('local edit requires a moving edge of at least 20 ticks')
    intermediate=[*(waypoint if waypoint is not None else a[:2]),a[2]+10]
    result['nodes']=nodes[:index+1]+[intermediate]+nodes[index+1:]
    return result


def build_local_profile(base,level,geometry):
    grid=base['grid'];horizon=base['horizon'];original=base['forecasts'][0]['obstacles'];revision=100
    eligible={}
    stubs=[]
    for o in original:
        edge=next((i for i,(a,b) in enumerate(zip(o['nodes'],o['nodes'][1:]))
                   if a[2]>revision and a[:2]!=b[:2] and 20<=b[2]-a[2]<=100),None)
        if edge is not None:eligible[o['id']]=edge
        stubs.append({'id':o['id'],'nodes':o['nodes'][edge:edge+2] if edge is not None else o['nodes'][-1:]})
    seed=base['metadata']['seed'];density=base['metadata']['requested_density']
    ids,positions,requested=select_obstacles(stubs,revision,level,geometry,rng_for(seed,density,level,'bounded-local'))
    plans=list(original);indices={o['id']:i for i,o in enumerate(plans)}
    per_agent={o['id']:dict(effective_reservations(base,{'reservations':obstacle_reservations(o,horizon)})) for o in original}
    occupancy=defaultdict(dict)
    for oid,cells in per_agent.items():
        for cell,intervals in cells.items():occupancy[cell][oid]=intervals
    prioritized=base['metadata']['obstacle_interaction_policy']=='prioritized'
    forbidden={tuple(base['start'][:2]),tuple(base['goal'][:2])};changes=[];events=[];support=set()
    for rank,oid in enumerate(ids):
        o=plans[indices[oid]];edge=eligible[oid];a,b=o['nodes'][edge:edge+2];r,c=a[:2]
        neighbors=sorted((r+dr,c+dc) for dr in (-1,0,1) for dc in (-1,0,1)
             if (dr or dc) and 0<=r+dr<len(grid) and 0<=c+dc<len(grid[0]) and grid[r+dr][c+dc]=='.'
             and (r+dr,c+dc) not in forbidden and [r+dr,c+dc]!=b[:2]
             and max(abs(r+dr-b[0]),abs(c+dc-b[1]))==1)
        # Alternate local detours and pause/catch-up edits. A detour rejection
        # falls back to catch-up, which only removes occupancy in this model.
        choices=[*neighbors,None] if rank%2==0 else [None]
        for waypoint in choices:
            candidate=mutate_local(o,edge,waypoint)
            current=dict(effective_reservations(base,{'reservations':obstacle_reservations(candidate,horizon)}))
            old=per_agent[oid]
            if prioritized and any(lo<=end and start<=hi
                 for cell in current for lo,hi in subtract_intervals(current[cell],old.get(cell,()))
                 for other,intervals in occupancy[cell].items() if other!=oid for start,end in intervals):continue
            size=change_size(base,{'reservations':obstacle_reservations(o,horizon)},
                                  {'reservations':obstacle_reservations(candidate,horizon)})
            if size['change_first_tick'] is None:continue
            if not a[2]-9<=size['change_first_tick']<=size['change_last_tick']<=b[2]+9:
                raise ValueError('local time support exceeded')
            event={'obstacle':oid,'mode':'local-waypoint' if waypoint is not None else 'local-pause-catchup',
                   'outcome':'applied','revision_tick':revision,'effective_tick':a[2],
                   'edge_index':edge,'intervention_end':b[2],'delta_first':size['change_first_tick'],
                   'delta_last':size['change_last_tick'],'waypoint':list(waypoint) if waypoint is not None else None}
            events.append(event);changes.append({'obstacle':oid,'before':o,'after':candidate})
            plans[indices[oid]]=candidate
            for cell in old:occupancy[cell].pop(oid,None)
            for cell,intervals in current.items():occupancy[cell][oid]=intervals
            per_agent[oid]=current
            support.update((tuple(a[:2]),tuple(b[:2])))
            if waypoint is not None:support.add(waypoint)
            break
        else:events.append({'obstacle':oid,'mode':'local','outcome':'no_effective_edit','revision_tick':revision})
    initial={'id':'initial','revision_tick':0,'events':[],'changed_obstacles':0,'reservations':base['forecasts'][0]['reservations']}
    after={'id':'local-change','revision_tick':revision,'events':events,'requested_changes':requested,
           'selected_obstacles':len(ids),'eligible_obstacles':len(positions),'changed_obstacles':len(changes),
           'changed_ids':[c['obstacle'] for c in changes],'reservations':reservations(plans,horizon)}
    before_cells=dict(effective_reservations(base,initial));after_cells=dict(effective_reservations(base,after))
    different={cell for cell in before_cells.keys()|after_cells.keys() if before_cells.get(cell)!=after_cells.get(cell)}
    if not different<=support:raise ValueError('local spatial support exceeded')
    if len(different)>3*len(changes):raise ValueError('too many cells in local change')
    def diameter(cells):
        return max(max(r+c for r,c in cells)-min(r+c for r,c in cells),
                   max(r-c for r,c in cells)-min(r-c for r,c in cells)) if cells else 0
    data={k:copy.deepcopy(base[k]) for k in ('schema_version','tick_seconds','horizon','grid','start','goal')}
    data['start_tick']=base.get('start_tick',0);data['forecasts']=[initial,after]
    data['metadata']={**base['metadata'],'suite_family':'upstream-bounded-local',
       'profile':f'{level}-{geometry}-local','spatial_pattern':geometry,'number_level':level,
       'selected_ids':ids,'selection_positions':{str(oid):positions[oid] for oid in ids},
       'changed_cells':len(different),'changed_cell_diameter':diameter(different),
       'normalized_cell_diameter':diameter(different)/(len(grid)+len(grid[0])-2) if len(grid)+len(grid[0])>2 else 0,
       'spatial_support':'at most 3 cells per accepted actor, within one neighbor step of its boundary',
       'temporal_support':'original edge window plus at most 9 ticks at either end from source merging',
       'deadline_preserved':True}
    for key in ('change_probability','change_probability_symbol','change_probability_unit'):data['metadata'].pop(key,None)
    return check_scenario(data),[{'forecast_id':after['id'],'revision_tick':revision,'changes':changes}]


def build_local_scenarios(source,output):
    source=Path(source).resolve();suite=json.loads((source/'suite.json').read_text())
    if not suite['complete']:raise ValueError('source scenario suite is incomplete')
    output=Path(output)
    if output.exists():raise ValueError('output exists; choose a new local scenario directory')
    output.mkdir(parents=True);cases=[];seen=set()
    config={'version':'bounded-local-v1','source_suite':str(source),
       'source_suite_sha256':hashlib.sha256((source/'suite.json').read_bytes()).hexdigest(),
       'generator_sha256':hashlib.sha256((ROOT/'sipp_baseline/local_scenarios.py').read_bytes()).hexdigest()}
    def save(complete):write_json(output/'suite.json',{'config':config,'cases':cases,'complete':complete})
    save(False)
    for case in suite['cases']:
        if case['tier']!='upstream':continue
        key=case['map'],case['seed'],case['density']
        if key in seen:continue
        seen.add(key);world=Path(case['directory']).parent
        base=load(source/world/'base.json');base_hash=scenario_digest(base)
        folder=output/world;folder.mkdir(parents=True)
        shutil.copyfile(source/world/'base.json',folder/'base.json')
        print(f'Bounded-local scenarios: {key}',flush=True)
        for level in ('few','many'):
            for geometry in ('cluster','spread'):
                data,trace=build_local_profile(base,level,geometry)
                data['metadata'].update({'base_scenario':'../base.json','base_sha256':base_hash})
                name=data['metadata']['profile'];info={k:case[k] for k in ('tier','map','seed','density','total_obstacles')}
                info.update({'profile':name,'number_level':level,'spatial_pattern':geometry,
                    'time_pattern':'bounded-local','history_pattern':'single',
                    'normalized_cell_diameter':data['metadata']['normalized_cell_diameter']})
                cases.append(save_case(output,str(world/name),data,base['forecasts'][0]['obstacles'],trace,info));save(False)
    save(True)
    return (output/'suite.json').resolve()
