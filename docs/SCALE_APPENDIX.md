# Scale preset (performance only)

This page is the 1,000-lot synthetic bay used by `make demo-bay` and the unit tests. It is not the public industry benchmark (SMT2020), and it is not the default console.

The preset is a seeded fab (`seed` 20261022): 1,000 lots and 36 tools across deposition, lithography, metrology, etch, clean, and CMP, on the same per-layer route as the six-lot stories. LITHO-03 is down for 600 minutes, and 24 priority-1 lots are blocked on it. The baseline is EDD dispatch: earliest due date, then the qualified tool that can start soonest, with no priority weight and no bottleneck lookahead.

| KPI | vs. EDD dispatch | Priority recovery |
| --- | ---: | ---: |
| On-time delivery | 100% | 100% |
| Priority-weighted tardiness | 0 min | 0 min |
| Priority-1/2 lots at risk | 0 | 0 |

Both books clear the dues. EDD already sends the 24 priority-1 lots to scanners that are up, and priority recovery leaves those lots on the same scanners. Mean wait between steps falls from 389 minutes to 125. Makespan grows from 4,522 minutes to 5,116 because lower-priority lots wait. Each product-layer has two physical reticles, and a copy that is not already on the scanner takes 5 minutes to mount. Schedule plus critic is about 0.7 seconds for 3,426 steps. Fourteen checks pass. The refused plan starts a blocked lot on LITHO-03 at time zero. Area utilization over the shared horizon stays near CMP 84.7%. The frame draws the first 12 hours as a per-tool load strip. LITHO-03 is hatched until the repair. CMP stays the bottleneck. The bay is staffed one operator per tool. `python scripts/export_scale_sql.py` writes `data/sql/scale_seed.sql` and `data/zetaris/scale/` for the same Zetaris catalog. `pytest` skips the 1,000-lot timer unless `RESILIMES_BENCHMARK=1`. CI runs a 40-lot smoke of the same generator.

On the 1,000-lot fab the two-second CP-SAT neighborhood does not beat the list schedule, so makespan stays 5,116 and the badge says the heuristic was kept.

The SMT2020 comparison, including the constructed book where earliest-due loses and the published-due performance tables, is in [SMT2020_SCALE.md](SMT2020_SCALE.md).
