import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from sipp_baseline.model import protocol
from sipp_baseline.runner import ROOT
from sipp_baseline.validation import oracle, validate


class TransferTests(unittest.TestCase):
    def test_clipped_empty_and_changed_projection_witnesses(self):
        # Initially impassable. Moving the decision tick clips the old source
        # domains. Removing the blocker later must reopen the cached empty edge.
        data = dict(grid=['.'*13], start=[0,0,0,0], goal=[0,12,0], horizon=160)
        blocked = dict(reservations=[[0,5,0,160]])
        clear = dict(reservations=[])
        sequence = [(dict(data,start_tick=t), f) for t,f in
                    [(0,blocked),(1,blocked),(2,clear),(3,dict(reservations=[[0,12,112,125]]))]]
        payload = ''.join(protocol(q,f,100000) for q,f in sequence)
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory)/'verify'
            subprocess.run(['g++','-std=c++17','-O1','-DSIPP_ADAPTIVE','-DSIPP_REPAIR_VERIFY',
                            str(ROOT/'src/incremental.cpp'),'-o',binary], check=True)
            proc = subprocess.run([binary,"0","5","--projection-reuse"],input=payload,text=True,capture_output=True,check=True)
        rows = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(rows),len(sequence))
        self.assertGreater(rows[1]['clipped_hits'],0)
        self.assertGreater(rows[1]['empty_hits'],0)
        self.assertGreater(rows[2]['projection_hits'],0)
        self.assertEqual(rows[2]['status'],'solved')
        for (q,f),row in zip(sequence,rows):
            self.assertEqual((row['status'],row['cost_ticks']),oracle(q,f))
            validate(q,f,row)
