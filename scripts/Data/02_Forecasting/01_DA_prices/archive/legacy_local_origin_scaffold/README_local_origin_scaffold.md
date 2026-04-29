# DA Price Forecasting Scaffold (NL, Hourly)

This folder contains the first forecasting scaffold for day-ahead (DA) NL prices.

Scope in this stage:
- Target: `price_eur_per_mwh` for `region == NL`
- Resolution: hourly only
- Forecast origin: daily at local `00:00` (`Europe/Amsterdam`)
- Forecast horizon: next 5 local days
- Validation/test evaluation: rolling-origin walk-forward

Fixed split policy (local dates):
- Train: `2022-01-01` to `2023-09-30`
- Validation: `2023-10-01` to `2024-09-30`
- Test: `2024-10-01` to `2025-09-30`

Current baseline models:
- `naive_1d`: same hour previous day
- `naive_7d`: same hour previous week

## Run

From project root:

```powershell
.\.venv\Scripts\python.exe scripts\Data\02_Forecasting\01_DA_prices\run_naive_benchmark.py
```

ARIMA/SARIMA benchmark vs `naive_7d`:

```powershell
.\.venv\Scripts\python.exe scripts\Data\02_Forecasting\01_DA_prices\run_arima_sarima_benchmark.py
```

ARIMA/SARIMA tuning sessions + final full run (with plots per model):

```powershell
.\.venv\Scripts\python.exe scripts\Data\02_Forecasting\01_DA_prices\run_arima_sarima_tuning.py --stage all
```

Outputs are written under:

`data/02_Forecasting/01_DA_prices/runs/<run_id>/`

Tuning outputs are written under:

`data/02_Forecasting/01_DA_prices/tuning_runs/<experiment_id>/`

with:
- split summary
- validation/test predictions
- metrics per split/model
- selected official naive reference on validation
- plots:
  - split overview (`train/validation/test`) with actual + forecast
  - best/worst test week zoom
  - best/worst test month zoom

## Next Models

Model placeholders are included for:
- ARIMA
- XGBoost
- LEAR

They can be plugged into the same backtest engine to keep evaluation fully comparable.
