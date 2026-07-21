# C5 Product Denominator And Slab-Import Boundary Policy

## Status

`decision_for_physical_reporting_with_opt_in_development_interface`; the
default physical baseline is unchanged. A separate C1 development interface
now tests source-tagged downstream material accounting.

## Decision

The C0/C1 model must report three distinct annual production measures.  They
must never be silently substituted for each other.

| Measure | Definition | C0 public context | C1 public context | Permitted use now |
|---|---|---:|---:|---|
| `endogenous_liquid_steel_t` | BOF plus EAF liquid steel made at IJmuiden. | 7.2 Mt/y | 6.8 Mt/y | Upstream route/material validation. |
| `imported_slab_t` | Explicit externally supplied slab entering the downstream site boundary. | 0.016 Mt/y | 0.6 Mt/y | Downstream boundary/context only; not a store or residual. |
| `site_final_product_t` | Finished rolled coils plus DSP rolls made at the site, irrespective of whether the slab origin is endogenous or imported. | 6.9 Mt/y | 7.0 Mt/y | Downstream/product validation. |

The 6.75 Mt/y development target remains useful as a **scenario quota**, but
it is no longer evidence that a 6.75 Mt/y `site_final_product_t` quota must be
satisfied entirely from endogenous liquid steel.  Until the imported-slab
route is implemented explicitly, it is an all-endogenous stress case rather
than a direct reproduction of the MER product boundary.

## Evidence And Interpretation

The official MER technical description states for C1 that:

- liquid-steel production falls from 7.2 to 6.8 Mt/y;
- slab import rises to 0.6 Mt/y; and
- final products remain about the same: 5.5 Mt/y rolled coils plus 1.5 Mt/y
  DSP rolls.

It explicitly relates the near-constant final-product volume to the higher
slab import.  The same MER gives C0/reference context of 16 kt/y slab import,
5.4 Mt/y rolled coils and 1.5 Mt/y DSP rolls.  These are annual site-boundary
anchors, not hourly plant capacities or free material supplies.

The current source cards correctly record the C1 0.6 Mt/y value as an
exogenous supply/validation anchor, not a slab-storage capacity.  The DSP
source card also records the MER route context as **C1 imported slabs to
HSM/WBW**.  This is sufficient to preserve the route as an annual
HSM-boundary check. The opt-in interface uses a clearly labelled uniform
annual-average delivery profile for a representative-horizon development test;
it is not an observed operational supply profile and is inactive by default.

## Required Boundary Accounting

When the physical route is later added, every tonne of downstream product must
have one origin tag:

```text
BOF endogenous liquid steel
EAF endogenous liquid steel
imported slab
```

The reporting balances are:

```text
site_final_product_t
  = HSM_WBW_product_from_endogenous_slab_t
  + HSM_WBW_product_from_imported_slab_t
  + DSP_product_from_endogenous_liquid_steel_t
  + DSP_product_from_imported_slab_t

endogenous_liquid_steel_t = BOF_liquid_steel_t + EAF_liquid_steel_t
```

The second relation deliberately does **not** include imported slab.  The
downstream conversion yield, internal scrap/loss, and any route-specific
reheating/electricity demand must remain visible rather than being absorbed in
a final-product conversion factor.

## Future Imported-Slab Interface

The later interface may be added only as:

```text
external slab supply with source-backed annual cap
  -> HSM/WBW (the currently source-mapped C1 destination)
  -> site final product
```

It must have all of the following properties:

- bounded by a declared C0/C1 annual context or scenario cap;
- no initial inventory, storage capacity, or implicit intertemporal borrowing;
- no contribution to endogenous liquid-steel production;
- no upstream BF/BOF/DRP/EAF energy, WAG, NG, or direct-fuel CO2 assigned to
  the imported material;
- downstream site electricity, fuel and explicit-fuel CO2 remain assigned to
  the actual downstream process that handles the slab;
- upstream embodied emissions remain out of scope unless an explicit external
  supply-chain boundary is opened later.

This means imported slab is neither a residual plug nor a way to calibrate an
anchor.  It is a source-backed external material boundary.

## Comparison Rules

| Question | Numerator | Comparator | Status |
|---|---|---|---|
| Does the upstream route make the intended steel? | `endogenous_liquid_steel_t` | C0 7.2 / C1 6.8 Mt/y | Primary when route boundary is coherent. |
| Does the site make the intended downstream product? | `site_final_product_t` | C0 6.9 / C1 7.0 Mt/y | Primary only after origin-tagged downstream routing. |
| What does the active development scenario request? | declared quota | 6.75 Mt/y | Scenario/reconciliation context; label its boundary. |
| What is process intensity? | process-specific activity basis | Matching process anchor | Never divide site energy or CO2 by an unrelated production measure. |

Negative electricity or NG residuals remain diagnostics.  They cannot be
eliminated by imported slab accounting, and imported slab cannot be used to
add unmodelled upstream energy or emissions.

## Immediate Implementation Sequence

1. **Origin-tag audit, no solve:** map current BOF/EAF/HSM/DSP final-product
   rows to the three origin tags and identify the missing route-origin links.
2. **Downstream portfolio interface:** add HSM/WBW and DSP product balances
   with explicit yields and product origins.  Keep imported-slab supply off
   until its eligible downstream destination is source-mapped.
3. **Two feasibility cases:** report an all-endogenous 6.75 Mt/y stress case
   separately from a MER-boundary site-product case with bounded slab import.
4. **Only then compare annual anchors:** compare upstream liquid steel and
   site final product on their own denominators; do not collapse them into one
   opaque score.

## Gates

`GO` for an opt-in C1 development feasibility case with the 0.6 Mt/y annual
context converted to a declared uniform annual-average cap, provided it stays
separate from cold-slab inventory and is reported as a scenario policy.

`NO-GO` for treating that profile as an observed delivery schedule, a default
baseline input, or a way to calibrate site-final-product anchors.

`GO` for using it now as a source-backed boundary explanation and annual
reporting anchor.

`NO-GO` for capacity/yield tuning in response to the present 6.75 Mt/y
infeasibility until the two production boundaries have been compared.

## Sources

- Royal HaskoningDHV / Tata Steel IJmuiden (2025), [*MER Heracless - Groen
  Staal, Deel B: Technische beschrijving*](https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf),
  section 4.3 and section 5.5, especially the annual material/output
  statements on pages 31 and 50.
- [DSP source card](../../../../data/03_Optimisation/inputs/assets/steel/source_cards/DSP_Parameters.md)
- [Buffers and storage source card](../../../../data/03_Optimisation/inputs/assets/steel/source_cards/BUFFERS_STORAGE_Parameters.md)

The first source is Rank 1 / Tier A evidence for the annual site boundary.  It
is not an hourly capacity, exact downstream-routing, or per-tonne-energy
source.
