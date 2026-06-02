# LEAR_STRICT Anchor Coverage Diagnosis (Phase 1b)

## Scope audited
- Full-run artifacts:
  - `data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/20260510_125919_lear_strict_observed_qh_grid_export_full_run/`
- Inputs:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/targets_by_origin.csv`
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/hourly_backbone_bridge_input.csv`
  - strict builder: `hourly_da.core.lago_multiday_features.build_lago_dplus4_direct_matrix_strict_no_future`

## Direct answers

### 1) Which forecast origins generated predictions, and which did not?
- Generated origins: **20/216** (all in `train` split), from:
  - earliest `2025-10-01 06:00:00+00:00`
  - latest `2025-12-29 07:00:00+00:00`
- Missing origins: **196/216**:
  - `train`: 109 missing
  - `validation`: 43 missing
  - `test`: 44 missing
- Full origin-level table is in `missing_origin_reason_table.csv`.

### 2) Exact reason for missing origins
Root cause is **upstream feature-matrix drop**, not prediction-loop failure:
- Full run `progress.json` shows `total_rows=1847` and `skipped_rows=0` in prediction loop.
- So uncovered rows were never present in the strict feature matrix / merge grid.

Dominant missing-origin reason classes (from strict builder diagnostics):
- `missing_p_base_d_minus_1` (most frequent)
- `missing_p_base_d_minus_2`
- `missing_p_base_d_minus_3`
- `missing_p_base_d_minus_7`
- `missing_x1_load_base_d`

These are exactly the required strict lag/exogenous inputs in the LEAR_STRICT builder.

### 3) Earliest and latest timestamp in `hourly_backbone_bridge_input.csv`
- Earliest: `2021-12-31T23:00:00+00:00`
- Latest: `2026-04-30T21:00:00+00:00`

After runner filtering (`price not null`, `not interpolated`, `not flagged`):
- Earliest: `2021-12-31T23:00:00+00:00`
- Latest: `2026-04-30T20:00:00+00:00`

### 4) Does bridge cover full observed-QH period up to `2026-04-29` origin?
- For anchor targets, grid requires:
  - min target: `2025-09-26T22:00:00+00:00`
  - max target: `2026-05-04T21:00:00+00:00`
- Bridge max is before that (raw `2026-04-30T21:00:00+00:00`, filtered `2026-04-30T20:00:00+00:00`).
- Therefore **tail coverage is incomplete** for late test origins.

### 5) Does bridge contain hourly prices constructed from post-transition QH?
- Yes.
- Post-transition rows (`>= 2025-10-01T00:00:00Z`) include:
  - `observed_hourly_from_observed_15min`: 4,992 rows
  - `derived_hourly_from_partial_or_nonobserved_15min`: 94 rows

### 6) Are missing validation/test anchors missing data or code filtering?
- **Missing data / feature availability**, not a split filter bug.
- Evidence:
  - `coverage_summary.csv`: validation/test 0%
  - strict overlap grid itself only has train origins (20)
  - prediction loop did not skip rows once rows were in the overlap grid
- Additional hard data boundary:
  - `da_total_load_forecast` max timestamp: `2025-12-31 23:00:00+00:00`
  - `da_res_generation_forecast` max timestamp: `2025-12-31 23:00:00+00:00`
  - so post-2025-12-31 strict exogenous requirements fail for later origins.

### 7) Can coverage be fixed without changing LEAR_STRICT methodology?
- **Yes, potentially**, if input coverage is extended while keeping the same strict no-future feature rules.

### 8) Exact change needed
Minimum needed before rerun:
1. Extend bridge input to cover full anchor target horizon through at least `2026-05-04T21:00:00+00:00`.
2. Extend strict exogenous inputs required by builder (`da_total_load_forecast`, `da_res_generation_forecast`) beyond `2025-12-31`.
3. Keep strict builder and model unchanged; only repair/extend data inputs.
4. Add preflight checks in runner (recommended) to fail early if:
   - exogenous max timestamp < anchor target max
   - bridge max timestamp < anchor target max

### 9) If not fixable, what assumption would need relaxation?
- If extended exogenous/bridge data cannot be produced, then any workaround would relax strict assumptions (e.g. fallback exogenous proxies or less strict observed-hour filtering), which becomes a **different model/input regime** versus current LEAR_STRICT strict setup.

## Conclusion
- Current 7.13% coverage and 0% validation/test are caused by **strict-feature input coverage limits**, not runtime logic.
- Next action classification is in `remediation_plan.json`.
