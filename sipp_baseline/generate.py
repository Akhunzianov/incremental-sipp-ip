"""Upstream SIPP-IP obstacle forecasts plus causal, seeded changes (probability q)."""
from collections import deque
from contextlib import ExitStack
import copy
import hashlib
import math
import random

from .model import check_scenario, integer
from .upstream_generator import PAPER_QUERIES, SOURCE_HASH, generate_base
from .obstacle_routes import StaticRoutes

SOURCE_HORIZON = 40000
DIRECTIONS = ((0,1),(-1,0),(0,-1),(1,0),(1,1),(1,-1),(-1,1),(-1,-1))


def canonical(reservations, horizon):
    cells = {}
    for r,c,a,b in reservations:
        a,b = max(0,a),min(horizon,b)
        if a <= b:
            cells.setdefault((r,c), []).append((a,b))
    result = []
    for (r,c), intervals in sorted(cells.items()):
        merged = []
        for a,b in sorted(intervals):
            # Upstream unions occupancy on its 1-second lattice before its
            # loader scales endpoints by F=10. Consecutive source slots merge.
            if merged and a <= merged[-1][1]+10:
                merged[-1][1] = max(b,merged[-1][1])
            else:
                merged.append([a,b])
        result.extend([r,c,a,b] for a,b in merged)
    return result


def obstacle_reservations(obstacle, horizon):
    nodes = obstacle['nodes']
    result = [row.copy() for row in obstacle['extra_reservations']]
    for first,last in zip(nodes,nodes[1:]):
        r,c,a = first
        nr,nc,b = last
        result.append([r,c,a,b])
        result.append([nr,nc,a,b])
    r,c,t = nodes[-1]
    result.append([r,c,t,horizon])
    return canonical(result,horizon)


def shortest_path(grid, source, goal, forbidden):
    source,goal = tuple(source),tuple(goal)
    parents = {source: None}
    queue = deque([source])
    while queue:
        r,c = queue.popleft()
        if (r,c) == goal:
            path = []
            node = goal
            while node is not None:
                path.append(node)
                node = parents[node]
            return path[::-1]
        for dr,dc in DIRECTIONS:
            nxt = r+dr,c+dc
            if (0 <= nxt[0] < len(grid) and 0 <= nxt[1] < len(grid[0])
                    and grid[nxt[0]][nxt[1]] == '.' and nxt not in forbidden and nxt not in parents):
                parents[nxt] = (r,c)
                queue.append(nxt)
    return None


def change_obstacle(obstacle, at_tick, mode, rng, grid, free, forbidden, horizon, route_via=None):
    """Change only after the next arrival, preserving an in-flight primitive."""
    nodes = obstacle['nodes']
    index = next((i for i,node in enumerate(nodes[:-1]) if node[2] > at_tick), None)
    if index is None or nodes[index][2] >= horizon:
        return None, None
    r,c,boundary = nodes[index]
    prefix = copy.deepcopy(nodes[:index+1])
    tail = copy.deepcopy(nodes[index:])
    event = {'obstacle':obstacle['id'], 'mode':mode, 'revision_tick':at_tick,
             'effective_tick':boundary, 'outcome':'applied'}
    if mode == 'pause':
        duration = rng.randint(1,10)*10
        tail = [[r,c,boundary], *[[rr,cc,t+duration] for rr,cc,t in tail]]
        event['pause_ticks'] = duration
    elif mode in ('accelerate','decelerate'):
        duration = next((b[2]-a[2] for a,b in zip(tail,tail[1:]) if a[:2]!=b[:2]), obstacle['base_step_ticks'])
        rebuilt = [tail[0]]
        profile = []
        for a,b in zip(tail,tail[1:]):
            if a[:2] == b[:2]:
                dt = b[2]-a[2]
            else:
                duration = max(10,min(100,duration+(-10 if mode=='accelerate' else 10)))
                dt = duration
            profile.append(dt)
            rebuilt.append([b[0],b[1],rebuilt[-1][2]+dt])
        if rebuilt == tail:
            event['outcome'] = 'unchanged_speed_bound'
            return None,event
        tail = rebuilt
        event['new_edge_ticks'] = profile
    elif mode == 'waypoint':
        path = None
        for _ in range(12):
            waypoint = rng.choice(free)
            if waypoint in ((r,c),tuple(obstacle['goal'])):
                continue
            if route_via:
                path = route_via((r,c),waypoint,obstacle['goal'])
            else:
                first = shortest_path(grid,(r,c),waypoint,forbidden)
                second = shortest_path(grid,waypoint,obstacle['goal'],forbidden) if first else None
                path = first+second[1:] if first and second else None
            if path:
                break
        if not path:
            event['outcome'] = 'no_waypoint_route'
            return None,event
        duration = next((b[2]-a[2] for a,b in zip(tail,tail[1:]) if a[:2]!=b[:2]), obstacle['base_step_ticks'])
        tail = [[rr,cc,boundary+j*duration] for j,(rr,cc) in enumerate(path)]
        event['waypoint'] = list(waypoint)
    else:
        raise ValueError(f'unknown change mode: {mode}')
    if tail[-1][2] > SOURCE_HORIZON:
        event['outcome'] = 'outside_source_horizon'
        return None,event
    result = copy.deepcopy(obstacle)
    result['nodes'] = prefix[:-1]+tail
    result['extra_reservations'] = [x for x in result['extra_reservations'] if x[2] <= boundary]
    return result,event


def generate(grid, seed=0, updates=5, obstacles=None, change_probability=.25, horizon=40000,
             start=None, goal=None, map_name=None, density=None, update_interval=100,
             generation_timeout=120, change_modes=('waypoint','pause','speed'), _base=None):
    integer(seed,'seed',0,2**32-1)
    integer(updates,'updates',0,10000)
    integer(update_interval,'update_interval',1,SOURCE_HORIZON)
    integer(horizon,'horizon',0,SOURCE_HORIZON)
    if not isinstance(change_probability,(int,float)) or not math.isfinite(change_probability) or not 0 <= change_probability <= 1:
        raise ValueError('change_probability q must be in [0,1]')
    if updates*update_interval > horizon:
        raise ValueError('forecast update times must lie within the horizon')
    if not change_modes or set(change_modes)-{'waypoint','pause','speed','accelerate','decelerate'}:
        raise ValueError('unsupported change modes')
    cells = [(r,c) for r,row in enumerate(grid) for c,cell in enumerate(row) if cell == '.']
    if len(cells) < 3:
        raise ValueError('obstacle generation needs at least three free cells')
    default = PAPER_QUERIES.get(map_name, ([*cells[0],0,0],[*cells[-1],0]))
    start = list(start if start is not None else default[0])
    goal = list(goal if goal is not None else default[1])
    data = {'schema_version':1,'tick_seconds':.1,'horizon':horizon,'grid':grid,'start':start,
            'goal':goal,'start_tick':0,'forecasts':[{'id':'p0','reservations':[]}]}
    check_scenario(data)
    if len(grid)>256 or len(grid[0])>256:
        raise ValueError('the upstream obstacle generator supports maps up to 256x256')
    if any(grid[r][c]=='#' for r,c in (start[:2],goal[:2])):
        raise ValueError('start and goal must be free')
    if density is not None:
        if obstacles is not None or not math.isfinite(density) or not 0<=density<=1:
            raise ValueError('choose either obstacle count or density in [0,1]')
        obstacles = math.floor(len(cells)*density)
    obstacles = 4 if obstacles is None else obstacles
    integer(obstacles,'obstacles',0,len(cells)-len({tuple(start[:2]),tuple(goal[:2])}))
    base = (generate_base(grid,seed,obstacles,start,goal,map_name,generation_timeout)
            if _base is None else copy.deepcopy(_base))
    trajectories = base['obstacles']
    reconstructed = canonical([row for o in trajectories for row in obstacle_reservations(o,SOURCE_HORIZON)],SOURCE_HORIZON)
    if reconstructed != base['reservations']:
        raise RuntimeError('captured obstacle paths disagree with the upstream reservation table')
    forbidden = {tuple(start[:2]),tuple(goal[:2])}
    free = [cell for cell in cells if cell not in forbidden]
    with ExitStack() as resources:
        router = resources.enter_context(StaticRoutes(grid,forbidden)) if change_probability and 'waypoint' in change_modes else None
        forecasts = []
        for revision in range(updates+1):
            at_tick = revision*update_interval
            events = []
            for i,obstacle in enumerate(trajectories) if revision else []:
                digest = hashlib.sha256(f'{seed}:{revision}:{i}:change'.encode()).digest()
                rng = random.Random(int.from_bytes(digest,'big'))
                if rng.random() >= change_probability:
                    continue
                mode = rng.choice(change_modes)
                if mode == 'speed':
                    mode = rng.choice(('accelerate','decelerate'))
                candidate,event = change_obstacle(obstacle,at_tick,mode,rng,grid,free,forbidden,horizon,router.via if router else None)
                if event is None:
                    continue
                if candidate is not None and map_name == 'empty_64_64':
                    others = {}
                    for other in trajectories:
                        if other['id'] == obstacle['id']:
                            continue
                        for rr,cc,a,b in obstacle_reservations(other,SOURCE_HORIZON):
                            others.setdefault((rr,cc),[]).append((a,b))
                    conflict = any(max(a,event['effective_tick'])<=v and u<=b
                                   for rr,cc,a,b in obstacle_reservations(candidate,SOURCE_HORIZON)
                                   if b>=event['effective_tick'] for u,v in others.get((rr,cc),[]))
                    if conflict:
                        event['outcome'] = 'rejected_obstacle_conflict'
                        candidate = None
                if candidate is not None:
                    trajectories[i] = candidate
                events.append(event)
            reservations = canonical([row for obstacle in trajectories for row in obstacle_reservations(obstacle,horizon)],horizon)
            forecasts.append({'id':f'p{revision}','revision_tick':at_tick,'events':events,
                              'obstacles':copy.deepcopy(trajectories),'reservations':reservations})
    data['forecasts'] = forecasts
    data['metadata'] = {'seed':seed,'obstacles':obstacles,'obstacle_density':obstacles/len(cells),
                        'obstacle_density_symbol':'p',
                        'requested_density':density,'change_probability':change_probability,
                        'change_probability_symbol':'q','change_probability_unit':'per obstacle per forecast revision',
                        'update_interval_ticks':update_interval,'generator':'sipp-ip-upstream-v2',
                        'map_name':map_name or 'custom','base_source_sha256':SOURCE_HASH,
                        'upstream_seed_policy':'std::mt19937 seeded with the requested uint32 seed',
                        'obstacle_interaction_policy':'prioritized' if map_name=='empty_64_64' else 'independent',
                        'change_modes':list(change_modes),'source_horizon_ticks':SOURCE_HORIZON}
    return check_scenario(data)
