# Visualisation Policy

## Purpose

This file is the required reference for thesis-ready plots, tables, notebook outputs, report figures, and recurring visualisation types.

It exists so visual reporting is consistent without keeping the full policy in `AGENTS.md`.

## General rule

Before creating a new recurring plot type, check this file. If the required figure type is not covered, add a chart-selection rule or figure contract here before producing thesis-ready visuals.

## Support statements

Every comparison plot or table should state, in the caption, note, nearby text, or run README:

- evaluated period;
- model or artifact set;
- strategy set;
- granularity;
- horizon;
- scenario count and scenario source where relevant;
- whether common support was used;
- whether values are optimisation-time expected metrics or realised settlement metrics;
- known caveats, especially scenario undercoverage or synthetic quarter-hour inputs.

## Chart-selection rules

- Forecast and scenario quality: use fan charts, realised-path overlays, coverage summaries, rank/cheap-window diagnostics, and tail-error panels.
- Bidding and clearing: separate submitted bids, cleared quantities, realised consumption, and settlement.
- Redispatch and settlement: keep physical dispatch, market positions, and realised financial outcomes visually separate.
- Production feasibility: show quota fulfilment, material balances, buffer states, WAG use/flare, steam/utility balances, residuals, and solver status.
- Benchmark comparison: show price-insensitive, perfect-foresight upper bound, and tested strategy on common support.
- CVaR/risk: show risk-return frontiers, VaR/CVaR markers, worst-tail outcomes, and realised position relative to scenario distribution.
- Solver and tractability: use appendix-grade tables or compact diagnostic charts unless tractability is a thesis claim.

## Semantic colour policy

Use stable semantic colours for:

- forecast/scenario model identity;
- strategy identity;
- market-chain stages such as submitted, cleared, dispatched, settled;
- infeasibility, warnings, and residuals;
- physical carriers such as BFG, COG, BOFG, NG, electricity, steam, and product/material streams.

Do not rely on default Matplotlib, Pandas, Seaborn, Excel, or notebook colour cycles for thesis visuals unless explicitly justified.

## Shared style module

The expected shared style entry point is:

- `src/reporting/visual_style.py`

When available, import and apply:

```python
from src.reporting.visual_style import (
    COLORS,
    MODEL_COLORS,
    STRATEGY_COLORS,
    MARKET_CHAIN_COLORS,
    apply_visual_style,
    save_figure,
)

apply_visual_style()
```

If this module is missing or stale, treat that as a documentation/code alignment issue before producing thesis-ready recurring figures.

## Anti-patterns

Avoid:

- unlabeled forecast/scenario support;
- expected-profit charts without realised-settlement context;
- profit charts without production fulfilment or feasibility context;
- hourly versus quarter-hour comparisons where other assumptions changed silently;
- synthetic quarter-hour paths shown as observed truth;
- stacked carrier plots that merge BFG, COG, BOFG, and NG into an unexplained aggregate;
- charts that imply ETS-ready or whole-site conclusions from a partial steel boundary;
- figures without units;
- visually polished plots that hide infeasibility, residuals, or solver warnings.

## Figure taxonomy

Thesis-body figures should answer the main research question with common support and clear caveats.

Appendix figures should carry:

- solver diagnostics;
- balance checks;
- input coverage diagnostics;
- run-level validation traces;
- sensitivity and robustness details;
- intermediate physical ledgers.
