# Backbone Routing Policy Implementation Report

## Patched file
- scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_export_for_qh.py

## Implemented changes
- Added explicit bridge source controls: `--bridge-source`, `--bridge-path`, `--bridge-market-area`.
- Added supported source `phase07_nl` routed to phase07 bridge file and NL filtering.
- Added bridge validation artifact per run: `phase07_bridge_validation_report.csv`.
- Added safer resume behavior: `--resume` no longer silently reuses latest run dir; explicit `--run-dir`/`--resume-dir` is required to attach.
- Kept LEAR_STRICT feature/model logic unchanged (instrumentation/routing only).
- Shortened internal skip-diagnostics filenames to avoid Windows path-length write failures.

## Approved bridge used
- `data\02_Forecasting\01_DA_prices\quarterhour_da\phase07_runs\20260505_134716_phase07_realistic_track_a\bridged_hourly_target_input_all_regions.csv`
- NL filtering applied on `region == NL` before strict feature construction.

## Validation highlights
- Filtered bridge rows: 37922
- Bridge covers anchor max timestamp: False
- Estimated full-grid overlap from Phase 1f: 24642/25920 (95.07%)

## Smoke result
- Run dir: `data\02_Forecasting\01_DA_prices\hourly_da\qh_anchor_exports\lear_strict_observed_qh_grid\20260511_094206_lear_strict_observed_qh_grid_export_backbone_routing_fix_smoke`
- Coverage: 360/360 (100.00%)
- Validation checks passed: True

## Decision
- A: Routing fix works and smoke is fully covered; estimated full-grid overlap is high (~95%). Full rerun is the next step.
