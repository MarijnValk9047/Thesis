# C6 Phase 6C QH DA Bid--Clear--Redispatch Gate

## Decision

`qh_da_bid_clear_redispatch_validated_on_bounded_common_week`

The shared steel bid--clear--redispatch engine is validated at 15-minute
resolution for the matched 27 April through 3 May 2026 period. This is a
bounded implementation and common-support comparison, not a long-run economic
evaluation, annual result, profit claim or isolated estimate of forecast-shape
value.

## Frozen scope

- configurations: C0 and C1;
- strategies: QH-point, risk-neutral QH-S10, price-insensitive and
  configuration-matched true PF;
- forecast origin: daily D-1 08:00 Europe/Amsterdam;
- planning: D--D+4, 120 hours/480 quarters;
- execution: D, 24 hours/96 quarters;
- campaign truncation: 480/480/480/384/288/192/96 intervals;
- QH forecast: `qh-fs1__mean_shape__hourly_anchor__lear_strict` from
  `20260729_strict_lear_dplus4_full_a03`;
- hourly comparator:
  `steel_phase6b_hourly_da_bid_clear_redispatch_a03_20260730`;
- terminal inventories: the accepted hourly bands, copied without QH target
  selection;
- solver: Gurobi, 900 seconds per lexicographic solve and 0.001 MIP gap limit;
  accepted results still require optimal termination.

No forecast training or tuning occurs. CVaR, mFRR, export, ETS, product
revenue, imbalance and emergency import remain inactive.

## Granularity contract

The physical builder uses an explicit `time_step_hours`. Source capacities and
fixed services are rates; model variables are interval quantities:

```text
interval quantity = hourly rate * time_step_hours
interval electricity cost = EUR/MWh * interval MWh
```

At QH resolution, 24-hour commitment and HSM blocks contain 96 intervals.
Production, route, scrap and generator deadlines remain elapsed physical-hour
contracts and are mapped to interval indices. Daily commitment binaries remain
daily. Historical fixed-hour schedules fail explicitly for QH. No unsupported
minimum-load, start, outage, CHP or plant ramp parameter is introduced. The
available QH physical flexibility is therefore an upper-bound development
abstraction.

The hourly `time_step_hours=1` regression reproduces all eight stored
Phase-6B normal-day trajectories. Maximum absolute represented-cost error is
EUR `1.86e-9`; maximum production error is `0.0 t`.

## Execution and acceptance

The governed run contains eight trajectories, 56 replans and 112 bidding or
redispatch model builds. It produces 86,016 bid rows and 5,376 realised QH
redispatch intervals. Every top-level model and every lexicographic tier is
optimal; all 203 checks pass.

All strategies produce approximately `129452.05479452055 t`. Every final state
records 168 executed hours, 672 executed intervals and last interval start
`2026-05-03T21:45:00+00:00`. Production, cumulative routes, material/carrier
balances, electricity, settlement, state handoff, hourly terminal bands,
zero-export and configuration-matched PF-dominance checks pass. QH point and
each QH scenario average back to their coupled hourly anchor within numerical
tolerance, with identical scenario IDs, weights and source blocks.

## Bounded common-support result

Costs below are realised represented procurement costs over seven days in EUR
million. `Delta` is QH minus hourly; negative values mean lower represented
cost in the QH implementation. Savings and regret use granularity- and
configuration-matched price-insensitive and true-PF references.

| Configuration | Strategy | Hourly | QH | Delta EUR m | Delta % | QH saving vs PI EUR m | QH regret vs PF EUR m |
|---|---:|---:|---:|---:|---:|---:|---:|
| C0 | point | 37.751 | 37.674 | -0.077 | -0.205% | 0.772 | 0.408 |
| C0 | S10 | 37.364 | 37.334 | -0.030 | -0.079% | 1.112 | 0.068 |
| C0 | price-insensitive | 38.743 | 38.447 | -0.297 | -0.766% | 0.000 | 1.181 |
| C0 | true PF | 37.295 | 37.266 | -0.029 | -0.078% | 1.181 | 0.000 |
| C1 | point | 60.820 | 60.760 | -0.061 | -0.100% | 1.905 | 0.316 |
| C1 | S10 | 60.720 | 60.636 | -0.083 | -0.137% | 2.028 | 0.193 |
| C1 | price-insensitive | 62.996 | 62.665 | -0.331 | -0.525% | 0.000 | 2.221 |
| C1 | true PF | 60.549 | 60.444 | -0.105 | -0.173% | 2.221 | 0.000 |

These deltas combine the effects of QH prices and QH physical flexibility. The
price-insensitive and true-PF rows also move, demonstrating why the result
cannot be interpreted as the value of QH forecast shape alone. Settlement,
other represented cost, cleared MWh, volume-weighted paid price, route totals,
inventories, intrahour MW variation and solver/model-size fields remain in the
compact generated comparison table.

QH-S10 p05--p95 evaluation coverage is 74.27%. It is a computationally matched
scenario sensitivity, not a calibrated 90% risk set.

## Artifacts and retention

Canonical implementation files are the shared Phase-6B/6C engine, QH wrapper,
runner, config and tests under `scripts/Data/04_Steel_Test_Case/`. Generated
run and comparison roots are local and ignored. The final retained bundle has
26 files and is approximately 29.63 MiB. Eight gzip checkpoints carry the run
fingerprint and one completed configuration/strategy trajectory each.

The checkpoints were initially emitted as uncompressed JSON. During post-run
retention normalization, a Windows permission failure removed those redundant
files before compression; they were reconstructed from the already validated
final bid, clearing, redispatch, state, solver and scenario tables, marked
`reconstructed_from_validated_final_outputs`, fingerprint-checked and read
back successfully. The accepted result tables, checks and summary were not
changed.
