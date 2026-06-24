# Final Aligned DAM Exports

Bounded one-off runner for the final aligned DAM forecasting export setup.

Purpose:
- Use the repaired LEAR Strict D-only 1092 anchor as the D-only hourly level source.
- Derive quarter-hour forecasts from the same hourly level plus the frozen canonical intra-hour deviation layer.
- Inspect the existing strict-no-future D+4 LEAR artifact without launching a long regeneration run.
- Preserve the 30-scenario requirement in generated orchestration commands.

Generated outputs are written under:

`data/02_Forecasting/01_DA_prices/dam_aligned_exports/`

This folder is generated forecast output and is not Git-eligible by default.
