# C5 WAG MILP Blocker Resolution Packet

## Result

C5p_z resolves the two builder defects that were already governed by existing
policy: KGF underfiring is now clean-COG-only in the base model, and the
builder reads selected LHV and point-of-oxidation combustion factors through
the C5 adapter. It also adds a **Mode B diagnostic** WAG combustion expression
that counts only represented BFG, COG and BOFG at their oxidation sinks.

This is not a complete site carbon ledger. Aggregate BF, BOF, KGF, PEFA,
sinter and EAF counters remain excluded, residual energy remains unallocated,
and no carbon cost, ETS term or dispatch incentive is activated.

## Mode B policy now active in the builder

- WAG carbon is counted once at represented combustion or flare sinks.
- Named placeholder/residual NG is not converted to CO2 by inference.
- Aggregate process counters cannot enter the Mode B subtotal.
- The expression is diagnostic-only: it does not alter the objective or route
  allocation.

## Directly resolved

- factor consistency: Selected C5p_y LHV and combustion-factor maps replace legacy builder constants.
- Mode B WAG CO2: Carrier-specific WAG oxidation is visible at represented sinks; no aggregate process counter or placeholder NG is added.

## Real stop conditions

- BF hot-stove controller: Select and register a C0/C1 executable hot-stove demand basis before adding a sink to the builder. Do not infer it from residual BFG.
- HSM/PEFA/boilers/generators: Promote each controller one at a time with its demand driver, carrier eligibility, capacity and output interface; boiler placeholders must be retired first.
- non-fuel process CO2: Obtain WAG-free/non-fuel carbon terms with explicit boundary and denominator before adding any process component.

## Controller readiness

- KGF underfiring: base route patched
- BF hot stove: no selected C0/C1 executable demand row
- HSM/WBW: no executable demand/controller contract
- PEFA: no executable fuel-demand contract
- boiler/steam: builder uses placeholder demand/cap
- VN25/IJ01: generic builder cap only

## Gate

- KGF COG-only base route and selected factor adapter: GO.
- Mode B explicit WAG combustion reporting: GO, partial diagnostic only.
- BF hot-stove, HSM, PEFA, boiler/steam and generator physical activation: NO-GO
  until their individual executable contracts are selected.
- Non-fuel process CO2, whole-site Scope 1/ETS, economics, DA and full
  sensitivity: NO-GO.
