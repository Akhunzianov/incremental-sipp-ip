# Bounded obstacle pulses

These six authored regression fixtures complement the random upstream-derived
controls. They are synthetic cases, not SIPP-IP paper samples. Their complete
inputs, trajectory deltas and canonical scenario fingerprints are versioned here.

The robot traverses a 13-cell corridor. Two or four obstacles initially move
between neighboring cells alongside it. At tick 10, their predicted future edges
are replaced with a waypoint through the corridor, starting at tick 40. Each
obstacle reaches its original endpoint at its original time; its future plan
then agrees exactly with the original. Each change affects at most three cells
for a short interval. Starts, goals, observed prefixes and actor counts stay fixed.

The old robot path becomes invalid. Waiting restores feasibility at a higher
optimal cost. The seed labels distinguish the fixed column/duration variations;
the saved inputs are the authoritative fixtures. `suite.json` registers them for
the standard comparison runner, which also checks the independent oracle.

```sh
python3 -m sipp_baseline compare-scenarios examples/diverse-pulses \
  --output runs/pulses-new
```

`tests/test_scenarios.py` audits every fixture, requires invalidation of the old
path, and checks both planners against the oracle.
