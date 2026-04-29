# Hourly DA Horizon Standardization

The hourly DA forecasting pipeline now uses the market-faithful local-day horizon:

- forecast origin: `08:00` on `D-1`
- delivery horizon: `D` through `D+4`
- lead-day labels: `D`, `D+1`, `D+2`, `D+3`, `D+4`

This is a 5 local-delivery-day horizon, not a fixed 120-step UTC horizon.
Most origins therefore produce 120 hourly targets, but DST transition windows can produce 119 or 121 UTC target hours.

Split-boundary handling is explicit:

- the pipeline no longer truncates late-split horizons
- forecast origins are generated only when the full `D..D+4` local-delivery horizon remains inside the split
- the split summary reports how many late-split origins are excluded for that reason
