# S3.0d Plant Boundary And Import Exposure Gate

## Scope

S3.0d-a freezes the interpretation gate for the current C0 and C1 WAG-energy diagnostics. It does not add DA prices, WAG price response, route optimisation, bidding, settlement, stochastic logic, CVaR, mFRR, product revenue, gross ETS cost, tariff logic, or market logic.

The C0 and C1 diagnostic calculations remain development mechanics. They are not Tata-exact plant operation, actual Vattenfall dispatch, cost accounting, or thesis validation claims.

## Current Diagnostic Status

C0 remains a `minimum_known_heat_sink_c0` diagnostic. It has valid WAG generation and allocation mechanics, but its annual-average electricity proxy and minimum-known coking heat sink do not close plant-level electricity, heat, or emissions boundaries.

C1 has three same-output route scenarios:

- `c1_high_drp_eaf`
- `c1_central`
- `c1_low_drp_eaf`

Each C1 scenario currently runs only as `component_energy_boundary_diagnostic`. The represented electricity boundary is DRP electricity plus EAF electricity. It excludes downstream electricity, auxiliary loads, residual fixed site load, complete heat/steam sinks, and complete direct emissions.

## Zero Component Import Warning

The C1 residual component grid import is zero in all three scenarios because WAG potential import offset is capped by the represented DRP/EAF component electricity demand.

This is a boundary warning, not a plant result:

- `component_zero_import_warning=true`
- `plant_level_import_interpretation_ready=false`
- `plant_level_power_offset_interpretation_ready=false`
- `plant_level_cost_accounting_ready=false`
- `cost_integration_ready=false`
- `da_market_integration_ready=false`

The zero component residual must not be described as plant-level zero grid import, cost saving, DA exposure, WAG financial value, export revenue, or actual dispatch.

## WAG Offset Meaning

`potential_net_import_offset` means a physical accounting potential within the represented boundary. For C1 S3.0d-a it means:

- WAG fuel is available structurally from retained BF, BOF, and coking drivers;
- represented DRP/EAF electricity demand is known;
- potential WAG-to-power output is capped by that represented component electricity demand.

It does not mean:

- actual Vattenfall generation;
- export;
- revenue;
- DA market dispatch;
- settlement;
- avoided cost;
- complete plant import reduction.

## Boundary Policies

The governed boundary policies are recorded in `s3_energy_boundary_policy_register.csv`.

Current selected interpretation:

- `component_only_lower_bound`: current C1 component diagnostic; not plant-level, not cost-ready, not DA-ready.

Future allowed but not selected in this task:

- `scaled_public_site_electricity_anchor_sensitivity`: sensitivity-only unless reviewed and scale-consistent.
- `component_plus_residual_site_load_assumption`: explicit user policy only, with sensitivity.
- `full_component_accounting_boundary`: target future boundary requiring downstream, auxiliary, heat/steam, natural-gas, WAG, and direct-emissions closure.

## Minimum Closure Before Cost Or DA Integration

Before S3 cost, ETS, or DA integration, the model must close or explicitly select:

- an electricity boundary: component-only lower bound, reviewed scale-consistent anchor, or explicit residual-load policy;
- a heat/steam boundary: at least retained process and broader steam/boiler sinks;
- a natural-gas boundary: DRP gas plus any boiler/process gas assumptions;
- a direct-emissions boundary sufficient to avoid double counting;
- a WAG offset interpretation policy distinguishing potential physical offset from actual dispatch.

Until those are selected and tested, C0/C1 diagnostics may support mechanics and directionality only.

## Readiness Freeze

The current readiness state is stored in `s3_cost_da_integration_readiness_register.csv`.

Frozen current interpretation:

- C1 component diagnostics are valid for same-output route comparison, DRP/EAF component gas/electricity demand, retained WAG comparison, potential offset mechanics, and partial emissions proxy.
- C1 diagnostics are not valid for plant-level import, plant-level electricity cost, DA exposure, WAG financial value, complete direct emissions, gross ETS, or complete site comparison.

## Recommended Next Step

Close the missing plant boundary before any S3.0 cost or DA market work: choose either an explicit component-only lower-bound interpretation for non-financial comparison, or select a reviewed residual/site-load policy with sensitivity and boundary caveats.
