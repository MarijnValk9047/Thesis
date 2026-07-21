# C1 Central Metallics WAG, Steam and Utility Reconciliation

## Purpose

This run combines the existing C1 central BOF/EAF metallics diagnostic with
the existing carrier-specific WAG, HSM/PEFA, boiler and generator surfaces.
It is an annualised representative-week reconciliation diagnostic, not an
economic optimisation or a whole-site annual claim.

## Included layers

- bounded BOF/EAF scrap and metallics ledger;
- BFG, COG and BOFG carrier balances only;
- existing HSM and PEFA fuel controllers;
- existing boiler-scaffold and generator-interface terms;
- source-traceable BF, BOF, KGF, DSP, ASU and sinter electricity boundary rows;
- a source-status representation-gap register for the next electricity layers;
- gross electricity, internal WAG generation offset and represented net import;
- named NG reported separately from the unresolved full-site NG residual;
- Mode-B WAG point-of-oxidation CO2 subtotal only.

## Boundary rules

- Aggregate and mixed WAG never feed a physical sink.
- C5p_k does not feed allocation.
- No WAG/NG ratio or Wobbe-quality rule is invented.
- No electricity or NG residual becomes a load, allocation or cost.
- BF, BOF, KGF, DSP, ASU and sinter electricity are activity-linked development rows,
  separately reported rather than hidden inside a generic site-electricity gap.
- WAG-explicit CO2 is not combined with aggregate BF/BOF/KGF/PEFA/sinter
  process counters and is not called Scope 1 or ETS-ready.
- The integrated boiler fuel balance now carries the C5p_b mapped existing
  demand as an explicit 15-bar mass-flow bridge.  It does not fill or claim
  unmodelled full-site steam demand, and it is not a detailed enthalpy model.

## Anchor policy

Official/MER records are secondary validation context where their existing
locator or boundary remains partial. Athanasiadis Table 9 is unscaled
model-precedent context, not official Tata truth. No anchor is a constraint.

When a labelled carrier-LHV sensitivity is active, it changes only the energy
represented by fixed BFG/COG/BOFG volumes. Table 9's WAG value is reported in
TWh and is therefore compared only with internal WAG-to-electricity output,
not with upstream WAG fuel energy in PJ. Neither comparison is a reason to
silently migrate a factor set into the base inputs.

## Result interpretation

Use `anchor_comparison.csv` only after first checking `guardrail_checks.csv`
and `wag_carrier_ledger.csv`. A closer value is never accepted if it results
from a guardrail failure, a boundary mismatch or a hidden residual.

`representation_gap_register.csv` is deliberately not a residual-load budget.
It distinguishes active source-traceable rows from bounded sensitivities and
deferred process layers, so that an annual anchor gap cannot silently activate
unrepresented electricity, NG or WAG use.

## Badarinath price-insensitive context

`plant_load_distribution.csv` reports the model's hourly price-free load
distribution by physical plant layer. `badarinath_price_insensitive_comparison.csv`
uses approximate visual bands transcribed from the user-supplied redacted
Badarinath figures. Those rows assess relative plant-load shape only: they are
not annual anchors, exact observations, constraints or calibration targets.
