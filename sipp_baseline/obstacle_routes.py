"""Speed up large waypoint experiments without changing BFS route selection."""
import json
import subprocess
from .runner import ROOT


class StaticRoutes:
    def __init__(self, grid, forbidden):
        source = ROOT/'src/obstacle_routes.cpp'
        binary = ROOT/'build/obstacle_routes'
        if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
            binary.parent.mkdir(exist_ok=True)
            subprocess.run(['g++','-std=c++17','-O2',str(source),'-o',str(binary)],check=True)
        self.process = subprocess.Popen([str(binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,text=True,bufsize=1)
        rows = [''.join('#' if (r,c) in forbidden else value for c,value in enumerate(row)) for r,row in enumerate(grid)]
        self.process.stdin.write(f'{len(grid)} {len(grid[0])}\n'+'\n'.join(rows)+'\n')
        self.process.stdin.flush()

    def via(self, source, waypoint, goal):
        self.process.stdin.write(' '.join(map(str,[*source,*waypoint,*goal]))+'\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('waypoint routing worker stopped unexpectedly')
        return json.loads(line)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()
