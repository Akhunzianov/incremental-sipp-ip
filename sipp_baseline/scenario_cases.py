"""Diverse causal multi-obstacle prediction sequences, plus engineered outcomes."""
from collections import defaultdict
import copy
import hashlib
import math
import random

from .diagnostics import change_size
from .generate import canonical, change_obstacle, obstacle_reservations
from .model import check_scenario

# A coverage matrix, not a full factorial design. Modes are mixed within batches.
PROFILES = (
    ('one-spread-near','one','spread','near','single'),
    ('few-cluster-near','few','cluster','near','single'),
    ('few-spread-near','few','spread','near','single'),
    ('many-cluster-near','many','cluster','near','single'),
    ('many-spread-near','many','spread','near','single'),
    ('all-eligible-near','all','spread','near','single'),
    ('many-spread-far','many','spread','far','single'),
    ('few-cluster-repeated','few','cluster','near','repeated'),
    ('many-spread-alternating','many','spread','near','alternating'),
)
MODES = ('pause','accelerate','decelerate','waypoint')


def rng_for(*parts):
    return random.Random(int.from_bytes(hashlib.sha256(':'.join(map(str,parts)).encode()).digest(),'big'))


def reservations(plans,horizon):
    return canonical([row for o in plans for row in obstacle_reservations(o,horizon)],horizon)


def select_obstacles(plans,threshold,level,geometry,rng):
    positions={o['id']:tuple(next(n[:2] for n in o['nodes'][:-1] if n[2]>threshold))
               for o in plans if any(n[2]>threshold for n in o['nodes'][:-1])}
    requested={'one':1,'few':4,'many':max(1,math.ceil(len(plans)*.25)),'all':len(plans)}[level]
    count=min(requested,len(positions))
    if not count:return [],positions,requested
    first=rng.choice(sorted(positions));anchor=positions[first]
    distance=lambda a,b:abs(a[0]-b[0])+abs(a[1]-b[1])
    if geometry=='cluster':
        selected=sorted(positions,key=lambda oid:(distance(positions[oid],anchor),oid))[:count]
    elif count==len(positions):selected=sorted(positions)
    else:
        selected=[first];remaining=set(positions)-{first}
        nearest={oid:distance(positions[oid],anchor) for oid in remaining}
        while len(selected)<count:
            nxt=max(remaining,key=lambda oid:(nearest[oid],-oid));selected.append(nxt);remaining.remove(nxt)
            for oid in remaining:nearest[oid]=min(nearest[oid],distance(positions[oid],positions[nxt]))
    return selected,positions,requested


def _data(base,profile):
    result={k:copy.deepcopy(base[k]) for k in ('schema_version','tick_seconds','horizon','grid','start','goal')}
    result['start_tick']=base.get('start_tick',0)
    result['metadata']={**base.get('metadata',{}),'suite_family':'upstream-multi-obstacle','profile':profile}
    for key in ('change_probability','change_probability_symbol','change_probability_unit'):
        result['metadata'].pop(key,None)
    return result


def build_profile(base,spec,reference,route_via):
    name,level,geometry,timing,history=spec;data=_data(base,name)
    horizon=data['horizon'];original=base['forecasts'][0]['obstacles'];plans=copy.deepcopy(original)
    revisions=[100] if history=='single' else [100,140,310] if history=='repeated' else [100,140,230,310]
    minimum=100 if history=='single' else 500
    if timing=='far':minimum=max(2000,(reference.get('cost_ticks') or 1900)+100)
    threshold=max(revisions[0],minimum-1)
    seed=base['metadata']['seed'];density=base['metadata']['requested_density']
    selected,positions,requested=select_obstacles(plans,threshold,level,geometry,
        rng_for(seed,density,level,timing,history,'selection'))
    forbidden={tuple(data['start'][:2]),tuple(data['goal'][:2])}
    free=[(r,c) for r,row in enumerate(data['grid']) for c,v in enumerate(row) if v=='.' and (r,c) not in forbidden]
    prioritized=base['metadata']['obstacle_interaction_policy']=='prioritized'
    forecasts=[{'id':'initial','revision_tick':0,'events':[],'changed_obstacles':0,
                'reservations':base['forecasts'][0]['reservations']}]
    trace=[];alternative=None
    for revision,at in enumerate(revisions,1):
        before=plans;events=[]
        if history=='alternating' and revision>1:
            plans=copy.deepcopy(original if revision%2==0 else alternative)
            for a,b in zip(before,plans):
                if a!=b:events.append({'obstacle':a['id'],'mode':'restore-original' if revision%2==0 else 'reapply-future',
                                      'revision_tick':at,'outcome':'applied'})
        else:
            plans=list(plans)
            indices={o['id']:i for i,o in enumerate(plans)}
            occupancy=defaultdict(dict)
            if prioritized:
                for o in plans:
                    for r,c,a,b in obstacle_reservations(o,horizon):occupancy[r,c].setdefault(o['id'],[]).append((a,b))
            for rank,oid in enumerate(selected):
                # Source obstacle IDs are contiguous, but lookup avoids assuming it.
                index=indices[oid];old=plans[index]
                rng=rng_for(seed,density,name,revision,oid)
                mode=MODES[(rank+rng_for(seed,density,level,'mode').randrange(4))%4]
                candidate,event=change_obstacle(old,max(at,minimum-1),mode,rng,data['grid'],free,forbidden,horizon,route_via)
                if candidate is None and mode in ('accelerate','decelerate'):
                    mode='decelerate' if mode=='accelerate' else 'accelerate'
                    candidate,event=change_obstacle(old,max(at,minimum-1),mode,rng,data['grid'],free,forbidden,horizon,route_via)
                event=event or {'obstacle':oid,'mode':mode,'outcome':'no_eligible_future'}
                event['revision_tick']=at
                if candidate is not None:
                    candidate['extra_reservations']=copy.deepcopy(old['extra_reservations'])
                    rows=obstacle_reservations(candidate,horizon);boundary=event['effective_tick']
                    if prioritized and any(max(a,boundary)<=end and start<=b
                          for rr,cc,a,b in rows if b>=boundary
                          for other,intervals in occupancy[rr,cc].items() if other!=oid for start,end in intervals):
                        event['outcome']='rejected_obstacle_conflict';candidate=None
                    if candidate is not None:
                        plans[index]=candidate
                        if prioritized:
                            for r,c,a,b in obstacle_reservations(old,horizon):occupancy[r,c].pop(oid,None)
                            for r,c,a,b in rows:occupancy[r,c].setdefault(oid,[]).append((a,b))
                events.append(event)
            if history=='alternating':alternative=copy.deepcopy(plans)
        changes=[{'obstacle':a['id'],'before':a,'after':b} for a,b in zip(before,plans) if a!=b]
        after={'id':f'revision-{revision}','revision_tick':at,'events':events,
               'requested_changes':requested,'eligible_obstacles':len(positions),'selected_obstacles':len(selected),
               'changed_obstacles':len(changes),'changed_ids':[x['obstacle'] for x in changes],
               'reservations':reservations(plans,horizon)}
        size=change_size(data,forecasts[-1],after)
        if size['change_first_tick'] is not None and size['change_first_tick']<=at:
            raise RuntimeError(f'noncausal generated change: {name}, revision {at}')
        forecasts.append(after);trace.append({'forecast_id':after['id'],'revision_tick':at,'changes':changes})
    data['forecasts']=forecasts
    data['metadata'].update({'number_level':level,'spatial_pattern':geometry,'time_pattern':timing,
        'history_pattern':history,'minimum_effective_tick':minimum,'selected_ids':selected,
        'selection_positions':{str(oid):positions[oid] for oid in selected},'requested_changes':requested,
        'eligible_obstacles':len(positions),'total_obstacles':len(original),
        'selection_rule':'cluster around common seeded anchor or farthest-point spread; never planner performance'})
    return check_scenario(data),trace


def engineered_cases(seed,count):
    """Guaranteed model-specific outcomes, explicitly not upstream random samples."""
    rng=rng_for(seed,count,'engineered');duration=rng.choice((20,30,40));far=220+10*rng.randrange(3)
    columns=sorted(rng.sample([5,6,7,8],count))
    specs=('benign','shortcut-opens','forced-delay','forced-detour','no-path-recovery','alternating-recovery')
    result=[]
    for family in specs:
        detour=family=='forced-detour';benign=family=='benign'
        cols=sorted(rng_for(seed,count,'detour').sample([4,5,6,7],count)) if detour else columns
        grid=['.'*13]*9 if benign else ['.'*9]*9 if detour else ['.'*13,''.join('.' if c in cols else '#' for c in range(13))]
        goal=[8,8,0] if detour else [0,12,0]
        data={'schema_version':1,'tick_seconds':.1,'horizon':400,'grid':grid,'start':[0,0,0,0],
              'goal':goal,'start_tick':0,'metadata':{'suite_family':'engineered','profile':family,'seed':seed,
              'obstacles':count,'obstacle_density':count/sum(row.count('.') for row in grid)}}
        def plans(depart,park):
            answer=[]
            for oid,c in enumerate(cols):
                source=[8,c] if benign else [1,c];target=[7,c] if benign else [0,c]
                nodes=[[*source,0],[*source,depart],[*target,depart+duration]]
                if not park:nodes.append([*source,depart+2*duration])
                answer.append({'id':oid,'start':source,'goal':target if park else source,
                               'base_step_ticks':duration,'extra_reservations':[],'nodes':nodes})
            return answer
        park=detour or family in ('no-path-recovery','alternating-recovery')
        initial=plans(40 if family=='shortcut-opens' or benign else 260 if detour else far,park)
        changed=plans(60 if benign else far if family=='shortcut-opens' else 20 if park else 40,park)
        sequence=[initial,changed];times=[0,10]
        if family=='no-path-recovery':sequence.append(initial);times.append(15)
        if family=='alternating-recovery':sequence=[initial,changed,initial,changed,initial];times=[0,10,12,15,18]
        forecasts=[];trace=[]
        for i,(world,at) in enumerate(zip(sequence,times)):
            changes=[] if not i else [{'obstacle':a['id'],'before':a,'after':b} for a,b in zip(sequence[i-1],world) if a!=b]
            f={'id':f'prediction-{i}','revision_tick':at,'reservations':reservations(world,400),
               'changed_obstacles':len(changes),'changed_ids':[x['obstacle'] for x in changes],
               'events':[{'obstacle':x['obstacle'],'mode':family,'outcome':'applied','revision_tick':at} for x in changes]}
            if i:
                assert change_size(data,forecasts[-1],f)['change_first_tick']>at
                trace.append({'forecast_id':f['id'],'revision_tick':at,'changes':changes})
            forecasts.append(f)
        data['forecasts']=forecasts
        result.append((check_scenario(data),initial,trace))
    return result
