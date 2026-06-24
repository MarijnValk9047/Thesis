# S3.0c-c C1 DRP/EAF Energy Inputs and Component Diagnostic

## Status

S3.0c-c does not select DRP/EAF energy coefficients and does not run a component-level or full C1 diagnostic.

The canonical source-evidence registers were checked for DRP natural-gas demand, DRP electricity demand, EAF electricity demand, DRP/EAF conversion basis, DRI yield, EAF yield, scrap share, DRI share, metallisation, and liquid-steel conversion evidence. No selectable source-backed candidate rows with complete locators were present.

The context research memos remain discovery aids only and are not primary source evidence for coefficient selection.

## Energy Input Decisions

The following inputs remain blocked:

- `drp_natural_gas_demand`;
- `drp_electricity_demand`;
- `eaf_electricity_demand`;
- `drp_eaf_output_conversion_basis`;
- `c1_site_electricity_demand_proxy`.

No missing value is set to zero. No hidden conversion is made between DRI, liquid steel, crude steel, HRC, pellets, or scrap share.

The existing route-share scenario inputs remain development-only user policy rows, not source-backed Tata-exact coefficients.

## Component Boundary

A component-based C1 demand boundary cannot yet be formed because the DRP and EAF electricity coefficients are missing. The C1 site-electricity cap remains blocked. Retained BF/coking WAG-generation drivers are available from the same-output profiles, but plant-level import-offset interpretation is not ready.

The heat and steam boundary remains incomplete. Retained C0-scaled coking and BF-side WAG drivers support WAG-generation-only validation, not full C1 energy allocation.

## Diagnostic Level

All three C1 scenarios remain at:

- `wag_generation_only`

They do not advance to:

- `component_energy_boundary_diagnostic`;
- `full_c1_plant_diagnostic`.

## Directional Comparison

Relative to C0, the C1 scenario profiles structurally reduce retained BF/coking activity as DRP-EAF share rises. Therefore BFG, COG, and BOFG generation drivers decline in the `c1_high_drp_eaf` case and rise in the `c1_low_drp_eaf` case.

The intended increase in natural-gas and electricity exposure cannot yet be quantified because the DRP/EAF energy coefficients are absent from canonical evidence.

No DA price, route optimisation, price-responsive WAG allocation, settlement, revenue, gross ETS cost, or tariff-cost layer is introduced.
