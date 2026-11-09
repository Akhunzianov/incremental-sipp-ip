import json
import random
import subprocess
import unittest

from sipp_baseline.model import protocol
from sipp_baseline.runner import ROOT
from sipp_baseline.validation import World, oracle, primitives


def reachable_ticks(query, forecast):
    world = World(query, forecast)
    root = (*query['start'], query['start_tick'])
    reached = set()
    pending = [root] if world.free(*root[:2], root[-1], root[-1]) else []
    while pending:
        state = pending.pop()
        if state in reached:
            continue
        reached.add(state)
        r, c, o, v, t = state
        if v == 0 and world.free(r, c, t, t+1):
            pending.append((r, c, o, v, t+1))
        for p in primitives(o, v):
            if world.legal(r, c, t, p):
                pending.append((r+p[4], c+p[5], p[1], p[2], t+p[3]))
    return reached


def departures(world, r, c, lo, hi, primitive):
    allowed = []
    for t in range(lo, hi+1):
        if world.legal(r,c,t,primitive):
            arrival = end = t+primitive[3]
            if primitive[2] == 0:
                while world.free(r+primitive[4],c+primitive[5],end+1,end+1):
                    end += 1
            allowed.append((t,arrival,end))
    return allowed


class WitnessAuditTests(unittest.TestCase):
    def test_support_is_reachable_after_root_and_occupancy_changes(self):
        subprocess.run(['make', 'build/witness_audit'], cwd=ROOT, check=True, capture_output=True)
        data = dict(grid=['.'*13], start=[0,0,0,0], goal=[0,12,0], horizon=160, start_tick=0)
        rng = random.Random(19)
        totals = dict(whole=0, partial=0, eligible=0, overlaps=0)
        for i in range(20):
            tick = rng.randint(40,50)
            query = dict(data, start=[0,4,0,1] if i%2 else data['start'], start_tick=tick)
            f = dict(reservations=[[0,rng.randrange(13),tick,tick+20]] if i else [])
            old = dict(reservations=[[0,9,0,160]])
            if i == 0:
                old = f = dict(reservations=[[0,9,0,160],[0,4,55,65]])
                query = dict(data,start_tick=1)
            payload = protocol(data,old,100000)+protocol(query,f,100000)
            proc = subprocess.run([ROOT/'build/witness_audit','--dump-support'],
                                  input=payload, text=True, capture_output=True, check=True)
            row = json.loads(proc.stdout.splitlines()[1])
            self.assertEqual((row['status'],row['cost_ticks']),oracle(query,f))
            truth = reachable_ticks(query,f)
            for key,lo,hi in row['support']:
                cell, ov = divmod(key,8)
                r,c = divmod(cell,len(data['grid'][0]))
                o,v = divmod(ov,2)
                for t in range(lo,hi+1):
                    self.assertIn((r,c,o,v,t),truth)
            self.assertEqual(len(row['eligible_domains']),row['eligible'])
            for key,lo,hi in row['eligible_domains']:
                cell, ov = divmod(key,8)
                r,c = divmod(cell,len(data['grid'][0]))
                for primitive in primitives(*divmod(ov,2)):
                    self.assertEqual(departures(World(data,old),r,c,lo,hi,primitive),
                                     departures(World(query,f),r,c,lo,hi,primitive))
            for field in totals:
                totals[field] += row[field]
        self.assertTrue(all(totals.values()),totals)
