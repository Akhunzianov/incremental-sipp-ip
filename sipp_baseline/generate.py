"""Seeded grid obstacle forecasts, saved as complete reservation snapshots."""
import random
from .model import check_scenario


def route(rng, grid, origin, horizon, mode, start_cell):
    r, c = origin
    tick, reservations = 0, []
    duration = rng.choice([5, 10, 20]) if mode == "speed" else 10
    waypoint = rng.choice([(rr, cc) for rr, row in enumerate(grid)
                           for cc, value in enumerate(row) if value == "."])
    while tick < horizon:
        candidates = [(r+dr, c+dc) for dr, dc in ((0, 1), (-1, 0), (0, -1), (1, 0))
                      if 0 <= r+dr < len(grid) and 0 <= c+dc < len(grid[0])
                      and grid[r+dr][c+dc] == "."
                      and (tick != 0 or (r+dr, c+dc) != start_cell)]
        pause = not candidates or (mode == "pauses" and rng.random() < 0.3)
        if pause:
            nr, nc = r, c
            dt = rng.choice([10, 20, 30])
        else:
            if mode == "waypoint" and rng.random() < 0.8:
                best = min(abs(rr-waypoint[0])+abs(cc-waypoint[1]) for rr, cc in candidates)
                candidates = [(rr, cc) for rr, cc in candidates
                              if abs(rr-waypoint[0])+abs(cc-waypoint[1]) == best]
            nr, nc = rng.choice(candidates)
            dt = duration
        end = min(horizon, tick+dt)
        # Both cells occupied throughout a move: conservative swept-grid model.
        reservations.append([r, c, tick, end])
        if (nr, nc) != (r, c):
            reservations.append([nr, nc, tick, end])
        r, c, tick = nr, nc, end
    if horizon == 0:
        reservations.append([r, c, 0, 0])
    return reservations


def generate(grid, seed=0, updates=5, obstacles=4, probability=0.25, horizon=500,
             start=None, goal=None):
    rng = random.Random(seed)
    cells = [(r, c) for r, row in enumerate(grid) for c, cell in enumerate(row) if cell == "."]
    if not cells:
        raise ValueError("map has no free cells")
    start = start if start is not None else [*cells[0], 0, 0]
    goal = goal if goal is not None else [*cells[-1], 0]
    # Validate geometry and state fields before using them to generate paths.
    check_scenario({"schema_version": 1, "tick_seconds": .1, "horizon": horizon,
                    "grid": grid, "start": start, "goal": goal,
                    "forecasts": [{"id": "check", "reservations": []}]})
    if grid[start[0]][start[1]] == "#" or grid[goal[0]][goal[1]] == "#":
        raise ValueError("generated scenarios require free start and goal cells")
    free = [(r, c) for r, row in enumerate(grid) for c, cell in enumerate(row)
            if cell == "." and [r, c] != start[:2] and [r, c] != goal[:2]]
    if obstacles > len(free):
        raise ValueError("too many obstacles for available initial cells")
    origins = rng.sample(free, obstacles)
    paths = [route(rng, grid, origin, horizon, "pauses", tuple(start[:2])) for origin in origins]
    forecasts = []
    for revision in range(updates+1):
        events = []
        if revision:
            for i, origin in enumerate(origins):
                if rng.random() < probability:
                    mode = rng.choice(["speed", "waypoint", "pauses"])
                    paths[i] = route(rng, grid, origin, horizon, mode, tuple(start[:2]))
                    events.append({"obstacle": i, "mode": mode})
        forecasts.append({"id": f"p{revision}", "events": events,
                          "reservations": [row.copy() for path in paths for row in path]})
    return check_scenario({"schema_version": 1, "tick_seconds": 0.1, "horizon": horizon,
                           "start": start, "goal": goal, "start_tick": 0, "grid": grid,
                           "metadata": {"seed": seed, "obstacles": obstacles,
                                        "update_probability": probability,
                                        "generator": "grid-walk-v1",
                                        "probability_unit": "per obstacle per forecast revision"},
                           "forecasts": forecasts})
