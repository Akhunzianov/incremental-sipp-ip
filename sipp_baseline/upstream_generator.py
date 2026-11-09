"""Build/run the authors' actual obstacle routines with a seed and route hooks."""
import hashlib
import json
from pathlib import Path
import subprocess

from .runner import ROOT

SOURCE_HASH = "75f66e8c6e3b5dde32578255505dbefc9c240c585bcfb9ac8d12d95119f9a622"
PAPER_QUERIES = {
    "empty_64_64": ([5,5,0,0], [59,59,0]),
    "room-64-64-16": ([6,6,0,0], [58,58,0]),
    "warehouse-10-20-10-2-2": ([4,4,0,0], [78,163,0]),
    "random128": ([5,6,0,0], [125,124,0]),
    "Sydney_2_256": ([31,23,0,0], [239,239,0]),
}


def build_generator():
    source = ROOT / "vendor/sipp-ip/src/generate_obstacles.cpp"
    adapter = ROOT / "src/obstacle_generator.cpp"
    binary = ROOT / "build/obstacle_generator"
    dependencies = [source, adapter, ROOT / "vendor/sipp-ip/include/constants.h", Path(__file__)]
    if binary.exists() and all(binary.stat().st_mtime >= p.stat().st_mtime for p in dependencies):
        return binary
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_HASH:
        raise ValueError("pinned obstacle generator source digest mismatch")
    text = raw.decode()
    temporal = 'if(tmp.x==NDX && tmp.y==NDY) {\n            for (int i = tmp.cost;'
    spatial = 'st_t = min(st_t, MXT-tmp.cost-1);'
    if text.count(temporal) != 1 or text.count(spatial) != 1:
        raise ValueError("upstream generator hook sites changed")
    text = text.replace(temporal, 'if(tmp.x==NDX && tmp.y==NDY) {\n            capture_obstacle(tmp, v, st_t, i_spd, true);\n            for (int i = tmp.cost;')
    text = text.replace(spatial, spatial+'\n            capture_obstacle(tmp, v, st_t, i_spd, false);')
    # Guard source accesses beyond its finite horizon, without changing valid transitions.
    text = text.replace('for(int k=tmp.cost; k<=tmp.cost+i_spd; ++k){',
                        'if(tmp.cost+i_spd>=MXT)continue;\n                    for(int k=tmp.cost; k<=tmp.cost+i_spd; ++k){')
    text = text.replace('tmp1.cost += i_spd;', 'if(tmp.cost+i_spd>=MXT)continue;\n                        tmp1.cost += i_spd;')
    text = text.replace('#include "../include/constants.h"', '#include "../vendor/sipp-ip/include/constants.h"')
    # The standalone file driver is unused (and has no explicit return).
    first = text.index('int main() {')
    last = text.index('\nvoid clr() {',first)
    text = text[:first]+text[last:]
    binary.parent.mkdir(exist_ok=True)
    (binary.parent / 'upstream_generator_instrumented.inc').write_text(text)
    subprocess.run(['g++','-std=c++17','-O2',str(adapter),'-o',str(binary)], check=True)
    return binary


def generate_base(grid, seed, obstacles, start, goal, map_name=None, timeout=120):
    binary = build_generator()
    name = map_name if map_name in PAPER_QUERIES else 'custom'
    fields = [len(grid),len(grid[0]),name,seed & 0xffffffff,obstacles,*start[:2],*goal[:2]]
    payload = ' '.join(map(str,fields))+'\n'+'\n'.join(grid)+'\n'
    result = subprocess.run([str(binary)], input=payload, text=True, capture_output=True, check=True, timeout=timeout)
    return json.loads(result.stdout)
