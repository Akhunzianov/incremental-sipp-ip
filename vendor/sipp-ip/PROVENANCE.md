# Upstream provenance

Repository: https://github.com/PathPlanning/SIPP-IP

Pinned commit: `77ca7491345c00b1cec7d0b88fe96cc561e0be25`

Retrieved 2026-11-09. `src/SIPP-IP.cpp`, `include/constants.h`, `README.md`,
and `LICENSE` are verbatim upstream files. Top-level `maps/*.txt` are verbatim
upstream map files. Upstream's other algorithms are omitted.

The 35 test-0 samples for the five benchmark maps are preserved under `tests/` as
lossless `.txt.gz` files; `tests/manifest.json` records their upstream paths and
SHA256 hashes of the original uncompressed bytes. Compression uses gzip with a
fixed timestamp. The release's additional `empty_1_16` toy instance is omitted.
`results/` contains the 35 matching saved SIPP-IP result files verbatim. These
released samples are not the full 200 instances per map and density described
in the paper. See https://arxiv.org/html/2302.00776 for the experiment setup.

Top-level `src/planner.cpp` adapts the motion primitive tables and interval
projection idea under the upstream MIT license. It replaces hard-coded file
I/O, dimensions, global search state, interval processing, queue management and
path reconstruction. New benchmark, validation and oracle code lives outside
this vendor directory.

`tests/upstream_reference.cpp` includes the unmodified upstream search under a
renamed main function. It supplies normalized reservations and blocks time after
the finite horizon to compare costs. It is only a verification adapter, limited
to stopped starts, maps up to 128x128, and horizons below 39999 ticks. It does
not apply our expansion limit and should only be used on small tests.
