"""Scenario format and input validation. All intervals are closed integer ticks."""
import json
from pathlib import Path


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def check_scenario(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("expected scenario schema_version 1")
    grid = data.get("grid")
    if (not isinstance(grid, list) or not grid or len(grid) > 1024
            or not isinstance(grid[0], str) or not 1 <= len(grid[0]) <= 1024):
        raise ValueError("grid must contain 1..1024 rows and columns")
    h, w = len(grid), len(grid[0])
    if any(not isinstance(row, str) or len(row) != w or set(row) - {".", "#"} for row in grid):
        raise ValueError("grid rows must have equal width and contain only '.' or '#'")
    horizon = integer(data.get("horizon"), "horizon", 0, 10_000_000)
    if data.get("tick_seconds") != 0.1:
        raise ValueError("the supported primitive model requires tick_seconds = 0.1")
    for name in ("start", "goal"):
        state = data.get(name)
        expected = 4 if name == "start" else 3
        if not isinstance(state, list) or len(state) != expected:
            raise ValueError(f"{name} must have {expected} integer entries")
        integer(state[0], f"{name}.row", 0, h-1)
        integer(state[1], f"{name}.column", 0, w-1)
        if name == "start":
            integer(state[2], "start.orientation", 0, 3)
        integer(state[-1], f"{name}.velocity", 0, 1)
    integer(data.get("start_tick", 0), "start_tick", 0, horizon)
    forecasts = data.get("forecasts")
    if not isinstance(forecasts, list) or not forecasts:
        raise ValueError("forecasts must be a nonempty list of complete snapshots")
    ids = set()
    for forecast in forecasts:
        if not isinstance(forecast, dict) or not isinstance(forecast.get("id"), str):
            raise ValueError("each forecast needs a string id")
        if forecast["id"] in ids:
            raise ValueError("forecast ids must be unique")
        ids.add(forecast["id"])
        if not isinstance(forecast.get("reservations"), list):
            raise ValueError("reservations must be a list")
        for reservation in forecast["reservations"]:
            if not isinstance(reservation, list) or len(reservation) != 4:
                raise ValueError("reservation must be [row, column, first_tick, last_tick]")
            r, c, lo, hi = reservation
            integer(r, "reservation.row", 0, h-1)
            integer(c, "reservation.column", 0, w-1)
            integer(lo, "reservation.first_tick", 0, horizon)
            integer(hi, "reservation.last_tick", lo, horizon)
    return data


def load(path):
    return check_scenario(json.loads(Path(path).read_text()))


def protocol(data, forecast, max_expansions):
    h, w = len(data["grid"]), len(data["grid"][0])
    fields = [h, w, data["horizon"], *data["start"], data.get("start_tick", 0),
              *data["goal"], max_expansions]
    lines = [" ".join(map(str, fields)), *data["grid"], str(len(forecast["reservations"]))]
    lines.extend(" ".join(map(str, row)) for row in forecast["reservations"])
    return "\n".join(lines) + "\n"


def read_map(path):
    """Read MovingAI .map or the authors' H W / 0 1 text maps."""
    text = Path(path).read_text()
    lines = text.splitlines()
    if lines and lines[0].startswith("type "):
        h, w = int(lines[1].split()[1]), int(lines[2].split()[1])
        if lines[3].strip() != "map":
            raise ValueError("invalid MovingAI map header")
        rows = lines[4:]
        if len(rows) != h or any(len(row) != w for row in rows):
            raise ValueError("map dimensions do not match data")
        return ["".join("." if c in ".GS" else "#" for c in row) for row in rows]
    words = text.split()
    h, w = map(int, words[:2])
    if h < 1 or w < 1 or len(words) != 2 + h*w or set(words[2:]) - {"0", "1"}:
        raise ValueError("invalid binary occupancy map")
    return ["".join("#" if x == "1" else "." for x in words[2+r*w:2+(r+1)*w]) for r in range(h)]
