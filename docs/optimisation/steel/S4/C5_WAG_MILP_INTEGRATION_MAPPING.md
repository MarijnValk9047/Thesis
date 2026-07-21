# C5 WAG-to-MILP Integration Mapping

## Result

The current `s4_4c_unified_physical_modelbuilder.py` contains a carrier-specific
minimal WAG layer, but it is **not eligible for activation as the thesis WAG
MILP layer**. It includes hard-coded boiler values, a fixed BFG/COG KGF split,
no active BF hot-stove controller, incomplete HSM/PEFA routes, and legacy flare
CO2 factors. C5p_x therefore makes no model change.

The historical builder default pointed to an obsolete input surface whose
blocker manifest no longer validated. It is now routed to the existing
validated S4.4b5a corrected-input surface; this repairs the baseline routing
only and does not alter any input value or WAG rule.

## Blocking repairs before an executable WAG layer

- **X_GAP_001 — KGF1 receives a fixed 50% BFG share.** Replace with COG-only governed KGF underfiring or explicitly reopen a source-backed sensitivity.
- **X_GAP_002 — Boiler fuel demand and WAG caps are hard-coded placeholders.** Map C5p_b boiler/steam controller inputs and eligibility before any reusable MILP integration.
- **X_GAP_003 — BF hot-stove demand is absent from active carrier balances.** Connect accepted hot-stove demand coefficients through a BF controller.
- **X_GAP_007 — No single executable source table covers all accepted carrier sinks and demands.** Create and validate one governed WAG model-input contract before builder changes.
- **X_GAP_008 — BF/BOF/KGF/PEFA/sinter/EAF aggregate process counters lack safe non-fuel separation.** Keep C5p_w exclusions until asset-specific source repair passes.

## What can proceed now

Create one governed WAG input adapter that maps existing accepted selected
inputs, demand coefficients and eligibility rows without promoting a new value.
It must reject placeholders, aggregate WAG, diagnostic-only controller rows and
routes with no source-backed demand basis. After that adapter exists, replace
the minimal layer incrementally under frozen 24-hour C0/C1 regression tests.

## Emissions consequence

The C5p_v explicit-fuel ledger remains the current authoritative diagnostic
subtotal. It must not be copied into the Pyomo model while the active WAG
routes still contain blocked placeholder logic. Aggregate BF/BOF/KGF/PEFA/
sinter/EAF counters and DRP capture remain separate.

## Gate

- WAG input-contract hardening: GO next.
- Activate/rewrite the physical WAG MILP layer: NO-GO pending blocking repairs.
- Attach explicit fuel-emissions expressions: NO-GO pending the WAG gate.
- Annual reconciliation and sensitivity execution: NO-GO pending the prior gates.
