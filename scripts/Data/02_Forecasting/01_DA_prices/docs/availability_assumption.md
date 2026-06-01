# DA Availability Assumption

The hourly DA pipeline uses an explicit `known_at` concept.

Why this matters:
- a DA price timestamp is a **delivery timestamp**
- it is not automatically the same thing as the moment that value became known to the forecaster
- if availability is handled incorrectly, the pipeline can hide information that should already be known at forecast time

Current simplifying assumption:
- forecast origin is `08:00` on `D-1`
- at that moment, the full DA curve for local day `D-1` is treated as already known
- the pipeline therefore assigns the same `known_at_utc` value to all hours of a delivery day
- for local delivery day `t`, `known_at_utc` is the UTC conversion of `t 08:00` local time

Interpretation:
- this is a conservative internal convention for the price series
- it is not a claim that the repo has verified the exact external publication timestamp for every DA family
- the pipeline is therefore internally consistent first, and market-faithful only to the extent that later audits confirm the simplifying rule is acceptable

Operational effect:
- history for model fitting and prediction is selected with `known_at_utc <= forecast_origin_utc`
- this allows the models to use the full previous local DA day at the forecast origin
- it avoids the incorrect rule `target_timestamp_utc < forecast_origin_utc`, which would wrongly hide the later hours of day `D-1`

Why this is a good current engineering choice:
- it matches the thesis requirement without overengineering the exact publication timestamp
- it is transparent and easy to audit
- later exogenous features can follow the same pattern by adding their own `known_at_utc` logic

Important nuance for exogenous features:
- the cleaned long exogenous source files carry their own family-level `known_at_utc`
- the hourly forecasting store is allowed to apply a stricter or corrected forecasting-time view before model fitting
- in particular, DA load and DA generation forecasts are corrected in the hourly forecasting store so that the day `D` forecast is available at the `D-1 08:00` origin used by the pipeline
- audit provenance should therefore distinguish the cleaned source-family timing from the final forecasting-store timing
