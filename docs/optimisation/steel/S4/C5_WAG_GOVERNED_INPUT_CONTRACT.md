# C5 Governed WAG MILP Input Contract

## Result

C5p_y creates one read-only adapter for selected WAG LHV and combustion-factor
rows, WAG eligibility and source-backed demand coefficients. It promotes no
new parameter and activates no route. It exposes **6** legacy
constant mismatches that must be removed before the Pyomo WAG layer is used.

## What is now safe to reuse

- selected BFG, COG and BOFG LHV values;
- selected WAG and named-NG combustion-factor rows;
- carrier-specific eligibility records, as structural evidence only;
- source-backed BF-hot-stove and C0 coking-demand records, as inputs awaiting
  a controller mapping.

## What remains blocked

- Current selected demand lists BFG/COG, while the current C5 base policy is COG-only.
- Demand coefficients exist, but no accepted sink mapping exists in the unified builder/eligibility surface.
- Eligibility or diagnostics exist without a complete executable demand/controller input contract.
- Legacy builder LHV and flare factors differ from governed selected values.
- Non-fuel process carbon remains source-separated NO-GO.

## Gate

- Governed read-only WAG input adapter: GO.
- Physical WAG MILP activation: NO-GO.
- Explicit fuel-emissions expressions in the MILP: NO-GO.
- Anchor sensitivity execution: NO-GO.
