# S3.1 Integration Freeze And S4 Entry Record

Date: 2026-06-19

## Decision

`S3.1-a` passed as a development-only downstream-aware deterministic energy and direct-emissions integration layer. `S3.1-b` reconciled the WAG activity basis and re-freezes the corrected integrated ledger.

S4 deterministic DA price-taking should not start until static-price input selection and a true S3 cost baseline are completed. Gross-load, explicit grid-import, natural-gas-import, and import-sensitivity preparation may continue. Actual WAG economic-value claims, static monetary cost claims, ETS claims, complete emissions claims, and plant-validation claims remain blocked.

## Passing Scope

The passing S3.1 layer:

- wraps the re-frozen S2 and S2.13 physical model;
- preserves hard final-product fulfilment;
- preserves C0 and C1 route shares;
- links downstream electricity and reheating heat to actual scheduled throughput;
- enforces WAG carrier balances with flare/spill residuals;
- uses reconciled WAG drivers: BFG from BF hot metal, COG from governed dry-coal proxy, and BOFG from BOF liquid steel;
- keeps WAG-to-power as potential-only no-export base dispatch;
- counts WAG direct emissions once at point of oxidation;
- counts C1 DRP direct CO2 proxy without separate DRP natural-gas combustion CO2;
- keeps scope-2 electricity emissions excluded;
- keeps monetary columns blank because selected static prices are missing.

## Mandatory Smoke Gate

Mandatory 24 h smoke cases passed:

- C0 integrated central: optimal;
- C1 central integrated: optimal;
- recoverable HSM outage: optimal;
- all-hot reference: optimal;
- cold-heavy diagnostic: optimal;
- hard-target stress: infeasible as intended.

Maximum material, WAG, electricity, and reheating residuals are zero within tolerance for feasible cases. Terminal inventory deviations are zero.

## S4 Entry Conditions

S4 may proceed only if it preserves:

- the fixed final-product target;
- S2/S2.13 physical feasibility and terminal rules;
- explicit grid import and natural-gas import;
- WAG no-disappearance and no-export constraints;
- reconciled WAG driver-basis mapping;
- no WAG revenue;
- no product revenue;
- no scope-2 emissions unless a governed factor is explicitly selected later;
- monetary readiness separation when prices are incomplete.

## Remaining Blocks

- no governed static grid-electricity, natural-gas, CO2, flare, startup, or tariff prices;
- WAG-to-power is not an actual dispatch/contract model;
- BF/BOF/coking residual direct emissions are incomplete;
- Tier-D downstream and residual-load coefficients require sensitivity hardening and stronger evidence;
- no DA settlement, stochastic, CVaR, mFRR, or product-revenue logic is permitted by this record.

## Git And Output Safety

This stage record does not represent a commit, tag, or release. No generated run folder is canonical evidence for S3.1-a.
