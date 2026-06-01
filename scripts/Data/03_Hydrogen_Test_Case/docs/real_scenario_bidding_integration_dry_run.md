# Real Scenario Bidding Integration Dry Run

## Purpose

Phase 6b is the first end-to-end real-scenario integration dry run for the hydrogen bidding stack:

1. load one hourly D-only scenario set from an integration-candidate artifact;
2. solve the validated risk-neutral stochastic hourly bidding MILP;
3. save the submitted bid curve;
4. clear those bids against the historical actual DA price path for the same day;
5. redispatch deterministically from the cleared electricity;
6. report expected scenario metrics and realised settlement metrics separately.

This is **not** thesis-grade evidence.

## Why this run is still non-thesis-grade

- the artifact is an `integration_candidate`, not a thesis-grade export;
- `forecast_origin_utc` was reconstructed upstream from:
  `D-1 08:00 Europe/Amsterdam converted to UTC`;
- hourly LEAR Strict scenario data is still missing on disk;
- only one forecast origin and one delivery day were used;
- this phase does not run a selected-week or full test-period experiment.

## Artifacts allowed in this phase

Phase 6b currently allows the clean one-variant exports created in Phase 6a-2:

- `hourly_lear_fs3_promoted_base_plus_b_integration_candidate`
- `hourly_xgboost_fs3_pruned_base_plus_b_integration_candidate`

These artifacts:

- contain 15 scenarios per forecast origin;
- validate probability mass at `1.0` per origin on the unique-scenario basis;
- preserve source provenance;
- remain non-thesis-grade because the forecast origin had to be reconstructed.

## Selection rule

If `--forecast-origin-utc` is not provided, the runner selects the first forecast origin that satisfies all of:

- exactly 15 scenarios;
- complete 24-hour hourly D-only delivery horizon;
- nonnegative probabilities summing to `1.0` over unique scenario IDs;
- complete actual historical DA prices for all 24 delivery hours.

## Command

```powershell
.venv\Scripts\python.exe scripts/Data/03_Hydrogen_Test_Case/run_real_scenario_bidding_dry_run.py `
  --config scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml `
  --artifact-id hourly_lear_fs3_promoted_base_plus_b_integration_candidate `
  --max-origins 1 `
  --strategy-name stochastic_bid_risk_neutral `
  --dry-run-label integration_candidate
```

## What is validated before solving

- artifact exists;
- artifact catalog validation mode is `smoke_test`;
- export manifest labels the artifact `integration_candidate`;
- reconstructed-origin warning is explicit;
- one forecast origin is selected;
- probabilities sum to `1.0`;
- 24 hourly delivery timestamps are present;
- actual historical DA prices exist for all 24 hours;
- timestamps are UTC;
- actual clearing uses `bid_price >= actual_price`;
- realised settlement uses actual price times cleared energy;
- redispatch respects `used + unused = cleared`.

## Expected objective vs realised settlement

The stochastic solve maximises **expected adjusted profit** over the scenario set.

The realised dry run then answers a different question:

- what happened when the fixed submitted bid curve was cleared against the historical actual DA price path?

So the run reports both:

- expected scenario-side objective metrics;
- realised ex-post clearing, redispatch, and settlement metrics.

They must not be treated as the same number.

## Optional benchmark comparison

Where feasible, the dry run also compares against the Phase 3c-style:

- `price_insensitive_plan_first_market_cap`

That comparison follows the existing chain:

- price-insensitive physical plan;
- one-block market-cap bid bridge;
- actual clearing;
- deterministic redispatch.

On a relatively cheap day, this benchmark can outperform the stochastic bid.

That is not a modelling failure by itself. It can happen when:

- realised prices stay low for many hours;
- the price-insensitive market-cap bridge clears almost everything;
- the stochastic bid leaves some late hours partially or fully unprocured because the scenario set priced more downside into those hours.

For a one-day dry run, the correct interpretation is:

- the pipeline worked;
- the strategy ranking is not yet stable evidence.

Before drawing conclusions about model quality or bidding quality, selected-origin or selected-week dry runs should include:

- volatile days;
- higher-price days;
- days with meaningful clearing tradeoffs.

## Output contract

The run folder saves:

- `submitted_bids.parquet`
- `actual_clearing.parquet`
- `actual_clearing_by_hour.parquet`
- `actual_redispatch_timeseries.parquet`
- `actual_settlement_results.csv`
- `scenario_clearing.parquet`
- `scenario_dispatch.parquet`
- `scenario_settlement_results.csv`
- `scenario_objective_summary.csv`
- `metrics_summary.csv`
- `validation_checks.csv`
- `input_manifest.json`
- `scenario_manifest.json`
- `model_stats.json`
- `README_real_scenario_dry_run.md`

## What still has to be fixed before thesis-grade runs

1. restore or regenerate a thesis-grade hourly scenario export with explicit `forecast_origin_utc`;
2. restore hourly LEAR Strict scenario data;
3. rerun the same integration path on thesis-grade artifacts only;
4. move from one-day dry run to selected-week and then proper test-period experiments;
5. keep scenario-quality diagnostics attached to every optimisation result.

## Why selected-origin dry runs come before selected weeks

The next scaling step is not a full selected-week experiment yet.

Selected-origin dry runs are used first because they let the pipeline cover different realised price regimes while still staying easy to audit:

- low-price days;
- typical-price days;
- high-price days;
- high-spread days;
- optionally peak-price days.

That is enough to check whether the stochastic strategy behaves sensibly across different realised environments before multiplying the run count further.

## How to interpret selected-origin dry-run results

These results are still integration diagnostics only.

They can show whether the stochastic strategy:

- changes clearing behaviour on expensive hours;
- preserves non-anticipative submitted bids;
- respects pay-as-cleared settlement;
- respects redispatch feasibility;
- sometimes outperforms and sometimes underperforms the price-insensitive benchmark in a plausible way.

On low-price days, benchmark outperformance remains plausible and should not be treated as a pipeline failure.

Patterns that would count as sensible behaviour at this stage are:

- lower clearing or more rejection in expensive hours;
- no use of uncleared electricity;
- small or zero unused energy unless physical limits bind;
- preserved hard validation checks across all selected origins;
- strategy differences that move with realised price level or spread, not random accounting noise.

What is still missing before thesis-grade experiments:

- thesis-grade hourly artifacts with explicit forecast origins;
- restored or regenerated LEAR Strict hourly scenarios;
- broader coverage over selected weeks and eventually the intended evaluation periods;
- continued scenario-quality diagnostics alongside every optimisation result.
