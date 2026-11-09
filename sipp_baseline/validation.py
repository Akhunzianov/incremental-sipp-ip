"""Independent concrete-action validator and bounded time-expanded Dijkstra.

Does not use the C++ interval projection, CLOSED handling, or reconstruction.
Primitive constants are intentionally duplicated and checked by the test suite.
"""
import heapq


def primitives(orientation, velocity):
    dr, dc = ((0, 1), (-1, 0), (0, -1), (1, 0))[orientation]
    if velocity == 0:
        yield "left", (orientation+1) % 4, 0, 20, 0, 0, [(0, 0, 0, 20)]
        yield "right", (orientation-1) % 4, 0, 20, 0, 0, [(0, 0, 0, 20)]
        contacts = [(0, 20), (0, 29), (20, 35), (28, 40), (34, 40)]
        yield "accelerate", orientation, 1, 40, 4*dr, 4*dc, [
            (j*dr, j*dc, a, b) for j, (a, b) in enumerate(contacts)]
    else:
        contacts = [(0, 6), (0, 12), (5, 20), (11, 40), (20, 40)]
        yield "brake", orientation, 0, 40, 4*dr, 4*dc, [
            (j*dr, j*dc, a, b) for j, (a, b) in enumerate(contacts)]
        yield "cruise", orientation, 1, 5, dr, dc, [(0, 0, 0, 5), (dr, dc, 0, 5)]


class World:
    def __init__(self, scenario, forecast):
        self.grid = scenario["grid"]
        self.horizon = scenario["horizon"]
        self.reservations = {}
        for r, c, a, b in forecast["reservations"]:
            self.reservations.setdefault((r, c), []).append((a, b))

    def free(self, r, c, first, last):
        return (0 <= r < len(self.grid) and 0 <= c < len(self.grid[0])
                and self.grid[r][c] == "." and 0 <= first <= last <= self.horizon
                and not any(first <= b and a <= last for a, b in self.reservations.get((r, c), [])))

    def legal(self, r, c, tick, primitive):
        return all(self.free(r+dr, c+dc, tick+a, tick+b) for dr, dc, a, b in primitive[-1])


def validate(scenario, forecast, result):
    if result["status"] != "solved":
        if result["cost_ticks"] is not None or result["steps"]:
            raise ValueError("unsolved result contains a path or cost")
        return None  # Feasibility of an unsolved result requires the oracle.
    world = World(scenario, forecast)
    state, tick = list(scenario["start"]), scenario.get("start_tick", 0)
    if not world.free(*state[:2], tick, tick):
        raise ValueError("path starts in a blocked cell")
    for step in result["steps"]:
        if step["from"] != state or step["start"] != tick:
            raise ValueError("discontinuous trajectory")
        r, c, o, v = state
        end = step["end"]
        if type(end) is not int or end <= tick:
            raise ValueError("action must have positive integer duration")
        if step["action"] == "wait":
            if v != 0 or step["to"] != state or not world.free(r, c, tick, end):
                raise ValueError("illegal waiting")
        else:
            choices = [p for p in primitives(o, v) if p[0] == step["action"]]
            if not choices:
                raise ValueError("action unavailable at this velocity")
            p = choices[0]
            expected = [r+p[4], c+p[5], p[1], p[2]]
            if end-tick != p[3] or step["to"] != expected or not world.legal(r, c, tick, p):
                raise ValueError("illegal primitive or collision")
        state, tick = step["to"], end
    if [*state[:2], state[3]] != scenario["goal"] or tick != result["cost_ticks"]:
        raise ValueError("wrong goal state or arrival time")
    return True


def oracle(scenario, forecast, max_states=2_000_000):
    """Exact within the declared finite horizon; raises if resource budget exceeded."""
    world = World(scenario, forecast)
    start = (*scenario["start"], scenario.get("start_tick", 0))
    if not world.free(*start[:2], start[-1], start[-1]):
        return "invalid_start", None
    queue = [(start[-1], start)]
    discovered = {start}
    while queue:
        tick, (r, c, o, v, _) = heapq.heappop(queue)
        if [r, c, v] == scenario["goal"]:
            return "solved", tick
        candidates = []
        if v == 0 and world.free(r, c, tick, tick+1):
            candidates.append((r, c, o, v, tick+1))
        for p in primitives(o, v):
            if world.legal(r, c, tick, p):
                candidates.append((r+p[4], c+p[5], p[1], p[2], tick+p[3]))
        for nxt in candidates:
            if nxt not in discovered:
                discovered.add(nxt)
                if len(discovered) > max_states:
                    raise RuntimeError("oracle state budget exceeded")
                heapq.heappush(queue, (nxt[-1], nxt))
    return "no_path", None
