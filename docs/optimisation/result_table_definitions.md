# Result Table Definitions

## Purpose

This file defines the expected result categories, table fields, and interpretation rules for optimisation reporting.

It is meant to keep run summaries, thesis tables, and future cleanup/promotion decisions aligned with the same metric vocabulary.

## Support Statement Requirement

Every comparison table should state, in the table note, caption, or nearby text:

- evaluated period;
- model or artifact set;
- strategy set;
- granularity;
- horizon;
- scenario count and scenario method where relevant;
- whether common support was used;
- whether the values are optimisation-time expected metrics or realised settlement metrics.

Without this support statement, a comparison can look cleaner than it really is.

## 1. Economic Metrics

These describe what value the strategy captures.

### Core fields

- realised net profit or realised net cost
- optimisation-time expected objective value
- uplift versus price-insensitive benchmark
- value captured versus perfect foresight benchmark
- DA electricity cost
- average electricity price paid
- hydrogen or product revenue
- production margin
- unused-energy or non-delivery penalty where applicable

### Interpretation rule

Expected objective value and realised settlement must remain separate fields. They answer different questions.

## 2. Risk Metrics

These describe downside exposure rather than average outcome alone.

### Core fields

- VaR
- CVaR
- worst-scenario profit or cost
- downside-tail mean
- realised outcome versus scenario distribution
- risk-return frontier coordinates where a gamma sweep exists

### Interpretation rule

Risk metrics should not be presented as robust evidence if the underlying scenario tails are known to be weak or undercovered without that caveat being stated.

## 3. Reliability And Feasibility Metrics

These show whether the strategy remains physically credible.

### Core fields

- production target fulfilment
- capped fulfilment ratio
- uncapped production-to-target ratio where above-target production is allowed
- unmet demand or shortfall
- storage boundary hits
- infeasible periods or failed validation checks
- grid-capacity violations if modelled
- reserve non-delivery once reserve products are added

### Interpretation rule

Profit should not be reported without feasibility context. A strategy that looks good economically but fails operationally is not a successful result.

## 4. Operational Metrics

These show how the plant actually behaved.

### Core fields

- electrolyser load profile
- compressor load profile where used
- storage trajectory
- ramping behaviour
- starts/stops if binaries are introduced later
- submitted vs cleared vs used electricity
- rejected energy
- price responsiveness
- consumption shifted from high-price to low-price periods

### Interpretation rule

Operational tables should help explain why an economic result occurred, not just confirm that a schedule existed.

## 5. Computational Metrics

These show whether the method is tractable and reproducible.

### Core fields

- solver status
- solve time
- MIP gap
- variable count
- binary variable count
- constraint count
- scenario count
- horizon length
- cache use / fingerprint information where relevant

### Interpretation rule

Computational metrics are appendix-grade by default, but they become headline metrics if tractability is part of the research claim.

## 6. Compact Thesis-Body Table

The compact thesis-body comparison table should usually include:

- strategy or model label
- granularity
- horizon
- realised net profit or cost
- production volume or fulfilment
- average price paid
- one downside-risk indicator
- uplift versus price-insensitive benchmark
- value captured versus perfect foresight

This table should remain readable without needing dozens of columns.

## 7. Appendix-Level Detailed Table

The appendix-level table should expand the metric set and include:

- field name
- definition
- units
- interpretation
- why it matters
- whether it is expected-value, realised-value, or support metadata

## 8. Table Promotion Rule

Large run-generated CSVs should not be treated as stable docs by default.

A table should be promoted into the Git-facing documentation layer only when it is:

- compact;
- interpretable without opening a run folder;
- tied to a stable metric definition;
- useful for thesis writing or future repo governance.
