# C5 C0 Schedule And Denominator Source Gate

> **Historical diagnostic.** The static-calendar evidence in this report is
> not the active C0 policy. Continue from the quota-driven baseline and C0
> continuous-operation gate in
> `C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md`.

## Decision

`NO_GO_FOR_C0_PHYSICAL_BASELINE_OR_ANNUAL_SCORING`.

The accepted C1 baseline is source-traceable. C0 has a reproducible negative
diagnostic, not an accepted physical baseline. The current C0 static calendar
is explicitly classified as an inherited historical regression profile, with
no primary availability locator. Its cokes shortfall is therefore conditional
on that profile and must not be generalised to the C0 route.

## Evidence Trace

| Item | Current evidence | Status | Consequence |
|---|---|---|---|
| C0 schedule | `steel_c0_source_corrected_schedule_basis_diagnostic_v5/c0_fixed_schedule_basis.csv` maps each YAML hour set to the corresponding Pyomo `*_on` variable | `historical` | Five KGF1, four KGF2 and nine BF6/BF7 hours/day reproduce the former regression only. |
| Cokes material basis | 1.285 t dry coal/t coke and 0.359 t coke/t hot metal from the coking and BF source cards | source-backed development basis | The old direct dry-coal-to-coke inventory treatment is corrected. |
| Conditional cokes result | 1,260.700 t/day maximum coke versus 2,070.947 t/day minimum BF demand | `fail` | The inherited 5/4/9-hour profile is not physically usable after the unit correction. |
| Coking and BF operation | MER/source-card interpretation says production-coupled and mostly/fully continuous | topology and operating logic only | It rules out hourly price response; it does not supply a numerical availability calendar. |
| C0 final-product target | 5,905.2 t/24 h in `production_targets.csv` is development-only | `historical` | Its 2.155 Mt/y representative-week annualisation is not a Tata annual denominator. |
| C0 final-product context | MER source cards report 5.4 Mt/y HSM/WBW plus 1.5 Mt/y DSP | Rank 1 annual context | It cannot become an hourly C0 constraint until the DSP route, material conversion and availability method are explicit. |

## Primary MER Check

The primary record is [MER Heracless - Deel B, 15 September 2025](https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf).
It states that the reference situation uses 7.2 Mt/y liquid steel when the
operational factories are used at an adequate level (section 4.2, p. 29). It
also reports 5.4 Mt/y rolled coils and 1.5 Mt/y DSP rolls, with cutting losses
already removed from those final-product volumes (section 4.3, p. 31). The
technical description gives a coking duration of about 18-22 hours (section
3.2.4, p. 17) and states that a coke-production margin is maintained because
the blast furnaces may not stop for technical reasons (section 4.3, p. 31).

The same primary record provides **no numerical KGF1/KGF2 or HO6/HO7
availability, maintenance or fixed-hour calendar** for the C0 reference case.
It therefore supports the continuous production-coupled topology and the
annual denominator, but does not promote the inherited 5/4/9-hour profile to a
source-backed fixed schedule.

## Promotion Conditions

The next C0 run may be treated as a configuration-matched physical reporting
surface only when all conditions below are met.

1. A primary-source or explicitly governed availability methodology fixes the
   KGF1/KGF2 and BF6/BF7 calendar before the solve. C0 binaries remain fixed;
   no optimiser schedule choice is introduced.
2. The C0 final-product denominator is an executable sum of origin-tagged HSM
   and DSP outputs. The MER annual figures remain validation anchors until the
   hour-to-year method is documented.
3. The C0 BF/sinter/burden basis has a coherent input-to-hot-metal conversion.
4. C0 electricity uses explicit non-overlapping activity drivers. Residual
   electricity and NG remain reporting quantities only.

## Explicit Non-Repairs

- Do not raise KGF/BF capacity, change coke yield, alter WAG factors or use a
  residual supply to close the current profile.
- Do not convert the C0 5.4/1.5/6.9 Mt/y public anchors directly into hourly
  dispatch without the availability and downstream-route methods above.
- Do not treat the existing DSP development layer as an executable C0 route
  until its source status, material interface and electricity boundary are
  promoted together.
