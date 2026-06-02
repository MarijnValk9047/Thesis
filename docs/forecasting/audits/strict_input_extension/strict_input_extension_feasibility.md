# Phase 1c Strict Input Extension Feasibility

## Objective
Extend strict LEAR input coverage for observed-QH anchor export through the required horizon using existing import and cleaning pipelines, without relaxing methodology.

## Existing pipelines used
- API imports:
  - `scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py`
  - underlying API utility: `scripts/Data/00_data_imports/API_GETS.py`
- Cleaning:
  - `scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_cleaning.py`
  - `scripts/Data/01_cleaning/entsoe_system_features_pipeline.py`
  - `scripts/Data/01_cleaning/day_ahead_prices_pipeline.py`
- Strict builder:
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/lago_multiday_features.py`
  - function: `build_lago_dplus4_direct_matrix_strict_no_future(...)`

## Security / API key handling
- Existing repo convention is `ENTSOE_KEY` (from `.env`), not `ENTSOE_API_KEY`.
- No key value was hardcoded or printed.
- API calls used environment lookup only.

## Required strict inputs and contracts
- `price_df` (bridge hourly price):
  - source: `hourly_backbone_bridge_input.csv`
  - required columns: `timestamp_utc`, `price_eur_per_mwh`, plus flags for filtering
  - timezone/frequency: UTC hourly
- `load_forecast_df`:
  - source: `data/01_cleaned_lago_lear_six_year/Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv`
  - required columns used downstream: `timestamp_utc`, `value_mw`, `known_at_utc`, `known_at_rule`
- `week_ahead_load_forecast_df` (fallback path in builder):
  - source: `.../Load/week_ahead_total_load_forecast/hourly/..._hourly_long.csv`
- `generation_forecast_df` (`x2`):
  - source used by strict run: `data/01_cleaned_lago_lear_six_year/Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv`
  - required columns: `timestamp_utc`, `value_mw`, `known_at_utc`, `known_at_rule`

Builder failure reasons previously observed (`missing_p_base_d_minus_*`, `missing_x1_load_base_d`) come from these strict required inputs when unavailable for an origin.

## What was run in Phase 1c
1. Imported 2026 raw ENTSO-E data with existing scripts:
   - load DA and week-ahead via `run_lago_lear_data_import.py`
   - A69 RES by PSR via `run_lago_lear_res_forecast_import.py`
2. Ran existing cleaning stack:
   - `run_lago_lear_cleaning.py` (A69 cleaner completed; family cleaner reported one failure)
   - reran required families directly with existing `entsoe_system_features_pipeline.py` (`da_total_load_forecast`, `week_ahead_total_load_forecast`) to complete load extension
3. Imported 2026 DA prices and reran existing day-ahead cleaning:
   - `day_ahead_prices_pipeline.py` for NL quarterly extension
4. Rebuilt bridge using existing observed-deterministic bridge function:
   - `quarterhour_da.observed_deterministic._build_hourly_bridge_from_quarterhour(...)`
5. Ran required exporter checks only:
   - `run_lago_lear_export_for_qh.py --check-only`
   - `run_lago_lear_export_for_qh.py --max-origins 3 --output-tag post_input_extension_smoke`

## Feasibility outcome
- Strict input coverage materially improved.
- Post-extension strict merge overlap now includes:
  - train origins: 28
  - validation origins: 10
  - test origins: 9
  - total overlap origins: 47
- This indicates validation/test coverage is now possible under the same strict methodology.

## Methodology integrity
- No proxy exogenous inputs introduced.
- No realised-future leakage paths introduced.
- Existing strict known_at logic and strict builder unchanged.
