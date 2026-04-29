# Time Handling

The pipeline stores forecast origins and target timestamps in UTC.

Business rules are still defined in market local time because the forecasting problem itself is stated in local delivery days:
- forecast origin: `08:00` on `D-1`
- target horizon: `D` through `D+4`
- this is interpreted as 5 local delivery days, so DST windows can produce 119 or 121 UTC target hours instead of exactly 120
- train / validation / test boundaries are given as local delivery dates

Implementation rule:
- generate delivery dates and origin timestamps in the market business timezone
- convert those timestamps to UTC immediately
- store only UTC timestamps in the forecast result tables
- convert back to local time only for reporting fields and notebook explanations

UTC audit result:
- raw DA XML periods enter with explicit UTC strings such as `2021-12-31T23:00Z`
- the cleaned hourly price file parses as timezone-aware UTC
- the upstream cleaning script constructs `timestamp_utc` with `utc=True`

Important caveat:
- the data is UTC-correct, but it is not gap-free
- the new forecasting pipeline therefore builds a canonical hourly UTC grid and keeps missing target hours explicit
- metrics only score rows with both `y_true` and `y_pred`
- for lag-based tabular models, the pipeline creates a deterministic feature-source series with a strictly causal fallback order:
  - first try the same UTC hour on the previous day
  - then try the same UTC hour on the previous week
  - then use the last earlier available observation as a final fallback
- no future interpolation is used for endogenous feature construction
- this feature-source series is used only for lag construction; evaluation still uses the observed target column

DA availability handling:
- the pipeline no longer decides availability from the delivery timestamp alone
- instead it stores a `known_at_utc` timestamp for each delivery day
- under the current thesis assumption, the full DA curve for local day `t` is treated as known from `t 08:00` local onward
- this means that at forecast origin `D-1 08:00`, the full DA curve for day `D-1` is available to the models

DST handling:
- target windows are defined as local delivery days and then converted to UTC
- this means DST transition days correctly produce 23 or 25 hourly targets instead of a hardcoded 24
- helper localization uses explicit `ambiguous='raise'` and `nonexistent='raise'` rules, so DST edge cases are not silently swallowed
