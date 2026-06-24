# S3.3i Athanasiadis Gas-Network Source Cards and 3 PJ Review

Status: diagnostic source-card review only. This note does not freeze S3.3, does not promote approved inputs and does not enter S4.

## Scope

S3.3i consolidates Athanasiadis gas-network evidence used by S3.3g and S3.3h and reviews whether the S3.3h boiler/steam values of 3 PJ/y natural gas and 3 PJ/y WAG have direct or indirect source support.

No model logic was changed and no calibration or C1 diagnostic was rerun.

## Source-Card Consolidation

The existing source-card material identifies the Athanasiadis thesis through `STEEL-SC-0021` and `F18_athanasiadis_tata_ijmuiden_thesis.md`. The `F18` card records the thesis as an uploaded local modelling-structure precedent and says the repo-local PDF was not found in the 2026-06-14 scan. The inspected master row does not contain the requested gas-network locators for Section 3.3.2, Figures 31-33, Table 9 or Figure 104. S3.3g already created a gas-network source-card register under candidate review. S3.3i adds a compact addendum at:

`data/03_Optimisation/inputs/assets/steel/source_evidence/athanasiadis_gas_network_source_card_addendum.csv`

The addendum records:

- Section 3.3.2 as structural support for WAG/process/boiler/generator gas-network representation.
- Figure 31 as structural support for main-plant gas sinks: HSM, Coking Plant 1, pelletizing firing and pelletizing grinding.
- Figure 32 as structural support for boiler/steam sinks.
- Figure 33 as structural support for Vattenfall generators and LHV-constrained gas mixtures.
- LHV values for COG, BOFG, BFG and NG, plus the generator upper mixture LHV around 5 MJ/m3.
- Table 9 and Figure 104 as Phase 1 validation-target context.

The direct PDF path provided for this review was not available locally, so the gas-network rows remain provisional thesis evidence pending direct PDF re-verification.

## Figure Ambiguity

The S3.3g register and prompt context indicate that the uploaded screenshots showing the main-plant gas controller correspond to Figure 31, while Figure 32 is the boiler/steam figure. S3.3i records this as a figure/caption ambiguity because the PDF could not be directly rechecked in this run.

## Conversion Check

For 3 PJ/y:

- 3,000,000 GJ/y.
- 342.465753 GJ/h average.
- At 37.5 MJ/m3 natural-gas LHV: 80,000,000 m3/y.
- At 37.5 MJ/m3 natural-gas LHV: 9,132.420 m3/h.

For the combined 6 PJ/y boiler/steam sink:

- 6,000,000 GJ/y.
- 684.931507 GJ/h average.
- 160,000,000 m3/y natural-gas equivalent at 37.5 MJ/m3.
- 18,264.840 m3/h natural-gas equivalent at 37.5 MJ/m3.

## Evidence Assessment

The review found structural support for boiler/steam gas sinks, WAG-to-steam use and broader site utility-boundary interpretation. It did not find a direct internal source for 3 PJ/y boiler natural gas, 3 PJ/y boiler WAG, or 6 PJ/y combined boiler/steam energy.

The 3 PJ/y NG and 3 PJ/y WAG values remain diagnostic-only gap-sizing values. The combined 6 PJ/y value is indirectly plausible as a broader utility-boundary sink, but unresolved numerically.

HSM NG at 9.300 PJ/y and pelletizing firing NG at 2.26008 PJ/y have stronger governed provisional support because they trace to process-heat ranges already used in S3.3g/S3.3h. They are still not approved inputs.

The Vattenfall BFG-equivalent WAG fraction of 1.0 remains diagnostic-only. The pathway is structurally supported, but the exact allocation fraction is not directly sourced.

## Classification

| S3.3h value | Classification | Decision |
| --- | --- | --- |
| 3 PJ/y boiler steam NG | Diagnostic-only | Keep diagnostic only |
| 3 PJ/y boiler steam WAG | Diagnostic-only | Keep diagnostic only |
| 6 PJ/y combined boiler/steam energy | Indirectly plausible | Keep diagnostic only |
| HSM NG 9.300 PJ/y | Provisional-source-supported | Do not approve automatically |
| Pelletizing firing NG 2.26008 PJ/y | Provisional-source-supported | Do not approve automatically |
| Vattenfall BFG-equivalent WAG fraction 1.0 | Diagnostic-only | Keep diagnostic only |

## Implication

S3.3h remains a gap-sizing diagnostic. S3.3 is not frozen and S4 is not ready. The next action is to verify Athanasiadis directly from a local canonical PDF and search targeted external/public Tata, PBL/TNO or Vattenfall evidence for boiler fuel quantities, steam balances and generator gas allocation.
