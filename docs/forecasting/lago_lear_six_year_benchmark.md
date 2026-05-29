# Lago LEAR Six-Year Benchmark

## Goal
Implement a reproducible Lago et al. (2021)-style LEAR benchmark for Dutch hourly day-ahead prices, plus a no-leakage D..D+4 thesis adaptation.

## Data Period
- Local delivery start: 2019-10-01
- Local delivery end (inclusive): 2025-09-30
- End exclusive: 2025-10-01
- Internal timestamp storage: UTC

## Import and Cleaning
Staged roots only:
- raw: `data/00_raw_lago_lear_six_year`
- cleaned: `data/01_cleaned_lago_lear_six_year`

Base ENTSO-E import:
```bash
.venv\Scripts\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py --dry-run --start-year 2019 --end-year 2025
```

A69 RES-by-PSR import:
```bash
.venv\Scripts\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py --dry-run --start-year 2019 --end-year 2025 --psr-types B16 B18 B19
```

Cleaning:
```bash
.venv\Scripts\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_cleaning.py --run-cleaning --raw-root data/00_raw_lago_lear_six_year --output-root data/01_cleaned_lago_lear_six_year
```

## Feature Definitions
Exact D-only structure (247 features):
- price lags: `p_(d-1), p_(d-2), p_(d-3), p_(d-7)` (96)
- current exogenous: `x1_d` load + `x2_d` RES forecast (48)
- lagged exogenous: `x1_(d-1), x1_(d-7), x2_(d-1), x2_(d-7)` (96)
- weekday dummies (7)

x2 mapping:
- preferred: A69 by-PSR sum `B16 + B18 + B19`
- fallback: aggregate DA generation forecast only when explicitly allowed

## D+4 Adaptation
Direct lead-day/hour models with strict known-at checks (`known_at_utc <= forecast_origin_utc`).

## Model Specification
- LEAR windows: 56, 84, 1092, 1456 days
- alpha selection: `LassoLarsIC(criterion='aic')`
- final fit: coordinate-descent `Lasso` on standardized features
- ensemble: arithmetic mean over available windows

## Runner
```bash
.venv\Scripts\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_six_year_benchmark.py --smoke-test --max-origins 3 --allow-official-cleaned-fallback
```

Heavy runs require explicit flags:
- `--run-d-only`
- `--run-dplus4`

## Outputs
Runs are written under:
- `data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear/<timestamp>_lago_lear_six_year_benchmark/`

Key artifacts include:
- `run_summary.json`
- `config_resolved.json`
- `data_sources.json`
- feature schemas and known-at audits
- predictions (`predictions_long.parquet`)
- coefficients (`coefficients_long.parquet`)
- metrics and diagnostics
- aligned comparison reports

## Limitations
- D+4 is an adaptation, not exact Lago.
- known_at assumptions are project-internal conservative assumptions.
- MAPE is reported but not a robust selection criterion for negative/near-zero prices.
- comparisons are valid only on aligned overlap timestamps and observed targets.

## Thesis Usage
Use this benchmark as a transparent reference model and clearly separate it from official FS-stage outputs and official split reporting.
