# Model Comparability

All hourly DA models in this workstream must share:
- the same cleaned hourly target series for the chosen market
- the same train / validation / test split policy
- the same daily rolling-origin logic
- the same forecast origin definition
- the same target horizon definition
- the same long-format forecast storage schema
- the same metric definitions

Comparable now:
- `naive_previous_week`
- `naive_previous_year`
- `lear_fs1`
- `lear_fs2`
- `xgboost_fs1`
- `xgboost_fs2`
- `prophet_fs2`

Naive benchmark policy:
- `naive_previous_week` and `naive_previous_year` are both evaluated in the dedicated `FS0` naive benchmark
- only the official naive benchmark selected on validation is carried into later benchmark suites and comparison notebooks

Closest comparable version for LEAR / XGBoost:
- LEAR and XGBoost share the same explicit-regressor design at `FS1` and `FS2`
- both are refit on the same rolling daily schedule and predict the same `D` through `D+4` target hours
- because the cleaned source has a small number of missing hourly prices, their lag features are built from a deterministic gap-filled feature-source series
- this keeps the rolling-origin horizon comparable instead of dropping large parts of the horizon whenever a single historical lag is missing
- because availability is now controlled by `known_at_utc`, the models can use the full previously published DA curve for day `D-1` at the `D-1 08:00` origin

Closest comparable version for Prophet:
- Prophet joins only at `FS2`
- it shares the same split chronology, forecast origin, target horizon, storage schema, and metrics as the other active models
- its closest fair setup is a compact causal `FS2` design with forecast-known calendar and holiday structure plus explicit endogenous regressors
- this is different from the tabular estimation style of LEAR and XGBoost, but it is still methodologically comparable because the evaluation pipeline and information set are aligned

Shortlisting policy:
- `FS1` is **not** the shortlisting stage
- the first fair shortlist point is after `FS2`
- only those `FS2` survivors should continue into `FS3`

Training-time monitoring:
- fit time is stored for every model-origin pair
- rolling summaries are stored in the run outputs
- warnings are triggered when fit time exceeds either:
  - an absolute threshold from config, or
  - a relative threshold above the model's recent rolling median
