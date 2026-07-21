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

### Fixed-reference deterministic steel-cost fields

The complete ex-post ledger and accepted fixed-reference economic runs populate
these fields from solved executed blocks:

- represented grid-electricity and named-NG cost;
- actual imported-slab cost;
- purchased coking-coal, PCI, represented ore, DR-pellet and scrap cost;
- total represented procurement cost and EUR/t executed site final product;
- reporting-only annualised cost from the same 168 executed hours;
- cost by represented flow, component, carrier/material and route;
- primary 168-hour cost objective, best bound, MIP gap and runtime;
- tie-break solution cost and residual to the primary optimum;
- residual electricity and NG quantities excluded from cost; and
- internal-generation offset.

Every table must identify whether it is ex-post or optimised, carry the active
price scenario or `price_series_id`, solved rolling lineage and route-cost
coverage. The accepted coverage label is
`adequate_represented_major_inputs_with_explicit_scope_gaps`; it does not imply
BF-pellet, HBI or full-site coverage. Results must not be labelled total site
cost, total production cost, profit, NPV or Tata procurement cost.

Residual energy, WAG purchase cost, internal-electricity/steam revenue, product
revenue and ETS must never be folded into these fields. Reference-validation
mode cannot produce a cost result. Fixed-reference route bands are scenario
definitions and remain excluded from independent anchor scores.

Price-series interface tables additionally report `price_series_id`, delivery
timestamp, market area, currency/unit, resolution, information-availability
timestamp, forecast/realised classification, missing-price policy, replan and
model-hour indices. Executed-block price fields remain labelled
`interface_only_not_settlement`; `DAM_bidding_active` and `settlement_active`
remain false until a later governed gate.

Bounded generator-response tables additionally report generator operating
mode, VN25 BFG/COG/BOFG/NG inputs, active efficiency, 350-MW development cap,
electricity output, grid import, carrier-specific flare, IJ01 fuel/output/
deferred-conversion status, steam, production, inventories and represented
procurement cost for every executed hour. They must show the analytical
`NG_price / efficiency` break-even and below/above-break-even dispatch totals.
Missing minimum-load/start/ramp/outage/CHP features are labelled
`omitted_not_zero`. The 4.1-PJ/y VN25-NG and 10.6-PJ/y generator-WAG-plus-flare
values remain post-run anchors and may not appear as constraints or fitted
targets.

Sensitivity tables report the changed price basket, price index, executed
cost, primary 168-hour objective, external quantity, elasticity and a reason
for fixed-route non-response. Executed-block totals and planned-horizon
objectives remain separate.

Fixed-reference acceptance tables must keep four production quantities
distinct: the 6.75-Mt/y central trajectory, the +/-0.5% permitted route
envelope, each complete 168-hour planned total, and the annual equivalent of
concatenated executed first blocks. The superseded v3 diagnostic annualised
the repeated first-block upper edge to 6.78375 Mt/y. The corrected
`steel_s2_pre_dam_operational_boundary_closure_v1_20260720` lineage must also
report carried production credit/debt, the next-block progress target and the
cumulative lower/upper envelope. Under flat prices, corrected executed blocks
annualise to 6.75 Mt/y without fixing hourly throughput. All annual equivalents
remain reporting views, not simulated calendar-year production.

Carrier-specific WAG tables must report configuration, BFG/COG/BOFG carrier,
source stage, sink stage/component, flow role, executed MWh LHV, annualised PJ
LHV/y, controller surface and physical/reporting status. Signed residuals may
not be floored. C0's generator sink may remain a carrier-specific aggregate
generator interface because no governed per-unit split exists; it may not be
labelled `aggregate_wag`, `mixed_wag` or a C5p_k allocation.

C0/C1 EUR/t may be shown side by side only with the label `represented
procurement cost`. They are not directly comparable total-production-cost or
route-economic results unless route portfolios, external-input coverage and
energy boundaries match. Cost waterfalls must include quantity, unit, price,
price unit, flow cost, category/route/configuration totals, source/origin
status, exclusions and explicit zero-cost internal/residual rows.

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
- material and origin conservation residuals for steel
- carrier-specific BFG/COG/BOFG balance residuals
- gross/internal/grid electricity identity residual
- named-NG component identity residual
- represented-steam demand/supply residual
- Mode-B exclusivity and residual-input exclusion status

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
- represented gross electricity by named non-overlapping bucket
- represented grid import and internal generation separately
- named NG by consumer and full-site residual separately
- generator fuel/electricity/steam/loss identity
- imported slab by origin with zero upstream site burdens

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
