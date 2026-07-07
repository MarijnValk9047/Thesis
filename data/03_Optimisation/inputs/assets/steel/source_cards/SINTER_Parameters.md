# SINTER Parameters Source Card

## Status

- Source-card status: candidate development memo
- Executable input table status: not executable by itself
- Thesis usability: false
- Human review required: true
- Codex may decide: false
- Stage scope: S4.4c5m Sinter minimal parameterisation

This memo records compact first-step Sinter Plant coefficients for a development-only C5 stage. The values are not Tata-validated, not thesis-approved, and must remain governed development candidates until targeted provenance and human review are complete.

## First Implementation Scope

The first Sinter abstraction is a continuous production-coupled plant link:

```text
iron_ore + electricity + COG/NG + steam
  -> Sinter Plant
  -> sinter + aggregate CO2 diagnostic
```

Sinter is a WAG consumer only. It must not create BFG, COG, BOFG, generic WAG, useful off-gas, or WAG export revenue in the base implementation.

## Core Candidate Coefficients

| Parameter | Candidate value | Unit | Status |
| --- | ---: | --- | --- |
| SINTER_BUS0 | iron_ore | material bus | development candidate |
| SINTER_PROCESS_CLASS | continuous_lp_link | class label | development candidate |
| SINTER_IRON_ORE_INPUT_T_PER_T_SINTER | 0.813 | t iron ore / t sinter | development candidate |
| SINTER_OUTPUT_T_PER_T_IRON_ORE_BUS0 | 1.230 | t sinter / t iron ore bus0 | development candidate |
| SINTER_ELECTRICITY_MWH_PER_T_SINTER | 0.0343 | MWh_e / t sinter | development utility proxy |
| SINTER_COG_INPUT_GJ_PER_T_SINTER | 0.067 | GJ_LHV / t sinter | development candidate |
| SINTER_COG_INPUT_MWH_PER_T_SINTER | 0.0186 | MWh_LHV / t sinter | development candidate |
| SINTER_STEAM_INPUT_T_PER_T_SINTER | 0.010 | t steam / t sinter | development utility proxy |
| SINTER_DIRECT_CO2_T_PER_T_SINTER | 0.248 | tCO2e / t sinter | development aggregate counter |
| SINTER_CO2_ACCOUNTING_MODE | aggregate_counter_mode | mode label | development candidate |

The output-to-bus0 value is greater than one because several real raw-mix inputs are omitted from the first-step bus abstraction. It is not a physical claim that iron ore mass increases.

## Sensitivity Metadata

These ranges are recorded for diagnostics only and are not activated in the base C5m run:

- Electricity: 0.0256 to 0.0431 MWh/t sinter
- Gas fuel: 0.035 to 0.185 GJ/t sinter
- Steam: 0.003 to 0.021 t/t sinter
- CO2: 0.162 to 0.368 tCO2/t sinter
- IPCC sanity value: 0.21 tCO2/t sinter
- EU ETS benchmark reference: 0.157 tCO2e/t sinter

## Development Coupling Anchors

Public MER context anchors used only to derive first-step coupling diagnostics:

- ANCHOR_SINTER_C0_OUTPUT = 3.7 Mt/y
- ANCHOR_SINTER_C1_OUTPUT = 2.8 Mt/y
- ANCHOR_SINTER_C1_OPERATIONAL_FLEX = 1.8 to 2.8 Mt/y
- ANCHOR_BF_C0_HOT_METAL = 6.3 Mt/y
- ANCHOR_BF_C1_HOT_METAL = 2.8 Mt/y

Derived development ratios:

- SINTER_PER_T_HOT_METAL_C0 = 3.7 / 6.3
- SINTER_PER_T_HOT_METAL_C1 = 2.8 / 2.8

These ratios are development coupling coefficients for the current C5 route diagnostics. They are not universal sinter burden recipes, not annual dispatch constraints, and not calibration targets.

## Exclusions And Caveats

The first-step abstraction excludes limestone, lime, dolomite, coke breeze, return fines, residues, detailed chemistry, off-gas, dust, gas cleaning, cooler heat recovery, waste-heat recovery, Sinter off-gas useful-WAG modelling, ETS objective steering, product revenue, DA price response, and Sinter ramp/flex scheduling.

Sinter aggregate CO2 is a diagnostic counter. When this aggregate counter is active, full Sinter COG or NG combustion CO2 must not also be booked as objective emissions or total direct CO2 unless a later governed carbon-accounting layer explicitly resolves the double-counting boundary.
