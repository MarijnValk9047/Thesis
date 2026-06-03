# Strict Input API Import Plan (Executed)

## Environment key convention
- Active convention in repo tooling: `ENTSOE_KEY`
- Read via:
  - `scripts/Data/00_data_imports/API_GETS.py` (`TOKEN_ENV_VAR = "ENTSOE_KEY"`)
  - `scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py` (`TOKEN_ENV_VAR = "ENTSOE_KEY"`)

No API key was passed on CLI or logged.

## Import scripts and purpose
1. `scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py`
   - imports:
     - `da_price`
     - `load_da`
     - `load_week_ahead`
2. `scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py`
   - imports NL A69 DA RES forecast by PSR:
     - `B16` solar
     - `B18` wind offshore
     - `B19` wind onshore

## Commands used

### 1) Load forecast extension (dry-run + run)
```bash
python scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py --dry-run --start-year 2026 --end-year 2026 --datasets load_da load_week_ahead --output-root data/00_raw_lago_lear_six_year
python scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py --run-import --start-year 2026 --end-year 2026 --datasets load_da load_week_ahead --output-root data/00_raw_lago_lear_six_year --skip-existing
```

### 2) A69 RES by PSR extension (dry-run + run)
```bash
python scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py --dry-run --start-year 2026 --end-year 2026 --output-root data/00_raw_lago_lear_six_year
python scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py --run-import --start-year 2026 --end-year 2026 --output-root data/00_raw_lago_lear_six_year --skip-existing
```

### 3) DA price extension for bridge tail (run)
```bash
python scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py --run-import --start-year 2026 --end-year 2026 --datasets da_price --output-root data/00_raw_lago_lear_six_year --skip-existing
```

## Cleaning commands used after import

### 4) Lago cleaner orchestration
```bash
python scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_cleaning.py --run-cleaning --raw-root data/00_raw_lago_lear_six_year --output-root data/01_cleaned_lago_lear_six_year --start-local-date 2019-10-01 --end-exclusive-local-date 2026-05-06 --local-timezone Europe/Amsterdam --regions NL
```

### 5) Existing family cleaner rerun for required load families
```bash
python scripts/Data/01_cleaning/entsoe_system_features_pipeline.py --raw-root data/00_raw_lago_lear_six_year --output-root data/01_cleaned_lago_lear_six_year --markets NL --families da_total_load_forecast week_ahead_total_load_forecast
```

### 6) Existing DA price cleaner for canonical quarterly source
```bash
python scripts/Data/01_cleaning/day_ahead_prices_pipeline.py --raw-root data/00_raw_lago_lear_six_year/DA_Prices --output-root data/01_cleaned/Day_ahead_prices --regions NL --quarterly-regions NL --cutoff-local-date 2025-10-01 --local-timezone Europe/Amsterdam --max-timestamp-utc 2026-05-12T00:00:00Z
```

## Bridge rebuild command path used
- Existing function reused:
  - `quarterhour_da.observed_deterministic._build_hourly_bridge_from_quarterhour(...)`
- Target file rebuilt in-place:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/hourly_backbone_bridge_input.csv`
