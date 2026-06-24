# S3.2 Freeze and S4 Entry Record

Date: 2026-06-19

## Decision

S3.2 is development-frozen as a static material-energy-carbon economics baseline for the represented S2.13 steel-site boundary.

## Gate Status

Passed:

- S2.13 physical regression remains valid.
- S2.13a slab-yard central capacity is selected at `25000 t` with preserved initial inventory `1630.13544 t`.
- Static material, electricity, natural-gas, and gross direct-carbon prices are selected.
- WAG generation uses the corrected S3.1-b carrier drivers.
- Practical WAG-to-power use is bounded by residual WAG fraction and no export.
- Scope 2 operational emissions are reported separately and excluded from ETS cost.
- Direct-carbon decomposition avoids DRP NG/proxy double counting.
- C0 and C1 fixed 24-hour static economic baselines solve.
- C1 endogenous-route 24-hour diagnostic solves.
- Recoverable outage and cold-heavy diagnostics solve.
- Hard-target stress remains infeasible.
- C0, C1 fixed, and C1 endogenous 168-hour runs solve.
- Cost, material, energy, WAG, and carbon balances reconcile within numerical tolerance.

## S4 Entry

S4 deterministic hourly DA price-taking may start from this baseline for static-to-hourly electricity-price exposure tests.

Conditions:

- Keep final production fixed.
- Do not add product revenue.
- Do not add stochastic scenarios, CVaR, mFRR, bidding settlement, export revenue, ETS free allocation, or CBAM in the first S4 step.
- Preserve the bounded WAG interface and no-export rule.
- Preserve route-cost coverage before any endogenous route run.
- Treat S3.2 material-price and BF-BOF carbon residual assumptions as development-only until strengthened by later evidence review.

## Remaining Risks

- Material prices are development assumptions and require public benchmark replacement.
- BF-BOF non-WAG residual direct emissions are a proxy, not a validated plant boundary.
- WAG-to-power utilisation is practical but not a physical Vattenfall dispatch model.
- Scope 2 uses static annual factors and does not represent hourly marginal emissions.
