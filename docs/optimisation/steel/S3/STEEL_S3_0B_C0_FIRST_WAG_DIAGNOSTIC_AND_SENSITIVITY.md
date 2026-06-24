# S3.0b-b3 C0 First WAG Diagnostic And Sensitivity

## Scope

This memo records the C0-only development-assumption closure, governed fixed-profile package, first central WAG diagnostic, and limited coefficient sensitivities for S3.0b. It does not approve thesis-grade inputs, does not modify S2, and does not create a C1 profile.

C1 remains deferred because the BF-BOF versus DRP-EAF route split is non-identified. The recorded feasible BF-BOF share interval remains approximately 0.5472 to 0.6799, and no midpoint or arbitrary solver split is selected.

## Accepted C0 Development Assumptions

All selected rows are development-only, non-approved, non-thesis-usable, and linked to complete canonical source locators.

| assumption | selected central | low | high | source cards | evidence rows | method |
|---|---:|---:|---:|---|---|---|
| coke rate per tonne hot metal | 0.29 t_coke/t_hot_metal | 0.27 | 0.31 | STEEL-SC-0001; STEEL-SC-0013 | STEEL-WAG-EVID-0049 | public_range_midpoint_modelling_assumption |
| dry coal input per tonne coke | 1.285 t_dry_coal/t_coke | 1.22 | 1.35 | STEEL-SC-0001 | STEEL-WAG-EVID-0050 | midpoint_modelling_assumption |
| C0 coking capacity proxy | 1500000 t_coke/year | n/a | n/a | STEEL-SC-0013 | STEEL-WAG-EVID-0051 | annual_average_proxy |
| coking underfiring fuel demand | 3.55 GJ_fuel/t_coke | 3.2 | 3.9 | STEEL-SC-0001 | STEEL-WAG-EVID-0052 | midpoint_modelling_assumption |
| coking plant steam demand | 0.43 GJ_useful_steam/t_coke | 0.06 | 0.80 | STEEL-SC-0001 | STEEL-WAG-EVID-0053 | midpoint_modelling_assumption |
| BFG hot-stove demand | 479.2 Nm3_BFG/t_hot_metal | n/a | n/a | STEEL-SC-0010 | STEEL-WAG-EVID-0054 | reference_model_development_assumption |
| COG hot-stove demand | 7.2 Nm3_COG/t_hot_metal | n/a | n/a | STEEL-SC-0010 | STEEL-WAG-EVID-0055 | reference_model_development_assumption |
| COG PCI drying demand | 1.4 Nm3_COG/t_hot_metal | n/a | n/a | STEEL-SC-0010 | STEEL-WAG-EVID-0056 | reference_model_development_assumption |
| C0 annual electricity-demand proxy | 3000000 MWh/year | n/a | n/a | STEEL-SC-0013 | STEEL-WAG-EVID-0057 | annual_average_proxy |

The C0 coking proxy is capacity-capped. On-site coke production is `min(coke_required, 1500000 / 8760 per hour)`. External coke receives no on-site COG credit. No coke storage, coking flexibility, or coking optimisation variable is introduced.

BOFG has no selected separate mandatory process sink for this diagnostic. BOFG remains eligible for shared steam/boiler use and then potential import offset.

## Fixed Profile

Created profile package:

`data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/fixed_profiles/c0_wag_fixed_profile_24h_dev.csv`

Profile metadata:

- `profile_package_id`: `c0_wag_fixed_profile_24h_dev`
- rows: 240
- configuration: `C0_current_BF_BOF_reference`
- content hash: `c7eeca9b9625a59fff89e28cd01d4e30cfc5c6984ff12e81b88c486e700a809b`
- extraction method: frozen S2 feasible-smoke model with C0 development WAG demand construction
- synthetic/diagnostic flag: true
- annual-average electricity proxy flag: true for the site-electricity-demand rows
- thesis usability: false

No C1 profile package is created.

## Central Diagnostic

Diagnostic classification: `minimum_known_heat_sink_c0`.

Validation status: `valid`.

Production profile totals:

- BF hot metal: 6520.54176 t
- BOF/liquid steel: 8150.67720 t

Coking proxy:

- on-site coke: 1890.95711 t
- external/imported coke: 0.0 t
- dry coal input: 2429.87989 t

WAG generation:

- BFG: 10432866.816 Nm3 and 34950.10383 GJ
- COG: 886906.15871 m3 and 16585.14517 GJ
- BOFG/LDG: 611300.79 Nm3 and 5856.26157 GJ

Use by sink:

- mandatory process use: 18229.08737 GJ
- steam/boiler use: 929.27035 GJ
- WAG-to-power fuel input: 38233.15285 GJ
- flare/spill/unused residual: approximately 0 GJ
- natural-gas boiler substitution: 0.0 GJ

Electricity:

- potential net-import offset: 3945.44897 MWh
- residual grid import: 4273.72911 MWh

Point-of-oxidation WAG CO2:

- BFG: 8646.65569 t CO2
- COG: 709.84421 t CO2
- BOFG/LDG: 1123.81659 t CO2
- natural gas: 0.0 t CO2

Balance and accounting:

- maximum balance residual: 1.14e-13 GJ
- total balance residual: 2.67e-12 GJ
- unmet mandatory demand: 0.0 GJ
- unmet steam demand: approximately 0 GJ
- direct emissions ledger complete: false
- gross ETS cost eligible: false

## Sensitivities

Executed coefficient-only low/central/high diagnostics:

- `cog_chain`
- `coking_process_demand`
- `coking_utility_demand`
- `bfg_generation`
- `bofg_generation`
- `conversion_efficiency`

No hierarchy, market, C1 route-share, Vattenfall capacity, export, revenue, or full-factorial sensitivity was run.

Selected sensitivity ranges:

| group | WAG generation GJ | potential import offset MWh | process use GJ | flare/spill GJ | WAG CO2 t | max residual GJ |
|---|---:|---:|---:|---:|---:|---:|
| cog_chain | 52052.59416 to 63769.61061 | 3448.89068 to 4549.24523 | 17766.12890 to 18692.04583 | ~0 | 10251.81087 to 10753.29918 | <= 2.28e-13 |
| coking_process_demand | 57391.51057 to 57391.51057 | 3877.15127 to 4013.74666 | 17567.25238 to 18890.92235 | ~0 | 10480.31650 to 10480.31650 | <= 2.28e-13 |
| coking_utility_demand | 57391.51057 to 57391.51057 | 3867.89004 to 4027.57018 | 18229.08737 to 18229.08737 | ~0 | 10480.31650 to 10480.31650 | <= 2.28e-13 |
| bfg_generation | 48653.98461 to 66129.03653 | 3043.78483 to 4847.11311 | 18229.08737 to 18229.08737 | ~0 | 8318.65257 to 12641.98042 | <= 2.28e-13 |
| bofg_generation | 55439.42338 to 59343.59776 | 3744.00441 to 4146.89352 | 18229.08737 to 18229.08737 | ~0 | 10105.71096 to 10854.92203 | <= 2.28e-13 |
| conversion_efficiency | 57391.51057 to 57391.51057 | 3409.12280 to 4481.77514 | 18229.08737 to 18229.08737 | ~0 | 10480.31650 to 10480.31650 | <= 1.14e-13 |

## Limitations

The diagnostic represents only selected mandatory process sinks and a minimum-known coking steam demand. Downstream heat sinks and complete site steam demand are omitted. Therefore the power/flare split is not an actual Tata dispatch claim. WAG power is reported only as `potential_net_import_offset`.

The annual electricity value is used only as a flat 24-hour development proxy. It is not observed hourly truth.

The emissions ledger is partial. It supports WAG and natural-gas point-of-oxidation accounting in the represented sinks, but it does not support complete site emissions or gross ETS cost.

## Readiness

C0 is runtime-ready for this minimum-known heat-sink development diagnostic.

C1 remains deferred after the C0 baseline because route share and retained coking basis remain unresolved.
