# S3.0b-b4 C0 WAG Interpretation Scale Validation And Freeze

## Status

The C0 central WAG diagnostic is reproducible from governed inputs and the governed fixed profile. Carrier balances close, COG is active, no export or revenue is represented, and WAG emissions are counted only at represented oxidation sinks.

This memo freezes mechanics only. It does not freeze the absolute WAG-to-power quantity, actual site grid import, actual flare, actual natural-gas substitution, complete site emissions, gross ETS cost, economic value, Tata-specific dispatch, or any C1 WAG balance.

## Scale Reconciliation

The fixed profile covers 24 UTC hours and is annualised using:

`annual_value = profile_24h_total * 8760 / profile_hours`

Annualised model scale:

- hot metal: 2379997.7424 t/year
- liquid steel: 2974997.178 t/year
- on-site coke: 690199.345296 t/year
- dry coal input: 886906.15870536 t/year

Canonical public anchors currently available in the candidate evidence:

- coking capacity proxy: 1500000 t_coke/year from `STEEL-SC-0013`
- site electricity proxy: 3000000 MWh/year from `STEEL-SC-0013`

No separate canonical candidate-evidence row currently gives a steel production or steel capacity reference value. Therefore `model_to_reference_steel_scale_ratio` is `not_assessable`.

The model-to-reference coking scale ratio is 0.460132896864. This is a material scale mismatch relative to the public annual coking-capacity proxy. The electricity proxy is also a full-site annual-average proxy that is not proven scale-consistent with the S2 profile boundary. No automatic rescaling is applied.

Interpretation consequence:

- WAG generation and balance mechanics remain valid.
- Per-tonne metrics remain valid as development diagnostics.
- Plant-level grid-import and plant-level power-offset interpretation are blocked.
- Absolute electricity outputs remain boundary-mismatched development diagnostics.

## Normalised Metrics

Production-normalised WAG generation:

- BFG: 1600 Nm3/t hot metal
- BFG: 5.36 GJ/t hot metal
- BFG: 4.288 GJ/t liquid steel
- COG: 365 m3/t dry coal
- COG: 8.7707675 GJ/t coke
- COG: 2.03481806 GJ/t liquid steel
- BOFG: 75 Nm3/t liquid steel
- BOFG: 0.7185 GJ/t liquid steel
- total WAG: 7.04131806 GJ/t liquid steel

Total WAG sink shares:

- mandatory process use: 0.317626896121
- boiler/steam use: 0.0161917736992
- potential power-interface use: 0.66618133018
- flare/spill/unused: approximately 0

Electricity metrics:

- potential net-import offset: 0.484063945993 MWh/t liquid steel
- residual grid import: 0.524340371895 MWh/t liquid steel
- potential-offset share of electricity proxy: 0.480029624434
- annualised potential offset at model scale: 1440088.8733014753 MWh/year
- annualised residual import at model scale: 1559911.1266988972 MWh/year

Emissions metrics:

- BFG oxidation: 1060.8512 kg CO2/t liquid steel
- COG oxidation: 87.090212968 kg CO2/t liquid steel
- BOFG oxidation: 137.88015 kg CO2/t liquid steel
- total WAG oxidation: 1285.821562968 kg CO2/t liquid steel
- natural-gas combustion: 0 kg CO2/t liquid steel
- partial-ledger completeness: false

These emissions are not compared to complete site-emissions anchors because the ledger boundary is incomplete.

## Warnings

The current C0 diagnostic triggers the following interpretation warnings:

- natural-gas substitution is zero because represented WAG supply exceeds the minimum-known heat demand;
- flare/spill is near zero because residual WAG is routed to a potential import-offset proxy;
- omitted downstream heat sinks make power-interface use an upper bound;
- the annual-average electricity proxy removes hourly site-load variation;
- production and electricity scale are not demonstrated consistent by a canonical production reference;
- complete site emissions are unavailable.

Zero natural gas and zero flare are not interpreted as desirable or validated plant behaviour.

## Readiness Taxonomy

Mechanics readiness:

- `wag_generation_mechanics_ready=true`
- `coking_proxy_mechanics_ready=true`
- `allocation_balance_mechanics_ready=true`
- `point_of_oxidation_emissions_ready=true`
- `coefficient_sensitivity_mechanics_ready=true`
- `minimum_known_heat_sink_mechanics_runtime_ready=true`

Plant-level and thesis readiness:

- `absolute_site_energy_scale_consistent=false`
- `downstream_heat_boundary_complete=false`
- `site_electricity_boundary_complete=false`
- `complete_direct_emissions_ledger_ready=false`
- `plant_level_import_interpretation_ready=false`
- `plant_level_power_offset_interpretation_ready=false`
- `plant_level_cost_accounting_ready=false`
- `s3_cost_integration_ready=false`
- `thesis_validation_ready=false`
- `plant_runtime_ready=false`

The current result has interpretation classes:

- `mechanics_validation`
- `minimum_known_heat_sink`
- `potential_import_offset_upper_bound`

It does not have `plant_accounting_ready`.

## Freeze Decision

Frozen for development mechanics:

- WAG generation mechanics for BFG, COG, and BOFG;
- C0 capacity-capped coking proxy mechanics;
- deterministic process-first allocation method;
- point-of-oxidation WAG emissions method.

Validated but not frozen as plant truth:

- current absolute sink split;
- current potential WAG-to-power quantity;
- current residual grid import;
- current zero natural-gas substitution;
- current near-zero flare.

Blocked:

- complete site heat and electricity boundary;
- complete direct-emissions ledger;
- gross ETS cost;
- economic value;
- C1 WAG balance.

## S3.0c Input-Closure Target

Before S3.0c cost integration, the next input-closure work must address:

1. throughput-coupled downstream electricity coefficients;
2. throughput-coupled downstream/process-heat coefficients;
3. broader steam/boiler demand boundary;
4. accounting-only auxiliary electricity loads including oxygen/ASU if selected;
5. explicit residual or fixed site-load policy;
6. scale-consistent production and electricity boundary;
7. non-WAG residual process-emission factors;
8. only after those are resolved: static commodity-cost accounting, gross ETS cost, and tariff proxy.

No S3.0c cost inputs, DA dispatch, market logic, or ETS-cost calculations are implemented here.
