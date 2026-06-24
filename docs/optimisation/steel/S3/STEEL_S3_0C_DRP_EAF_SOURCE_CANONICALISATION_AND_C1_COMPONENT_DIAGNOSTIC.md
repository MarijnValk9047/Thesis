# S3.0c-d1/d2 DRP/EAF Source Canonicalisation And C1 Component Diagnostic

## Scope

This note records the S3.0c-d1 source-gap result and the S3.0c-d2 corrective pass under the revised S3 evidence-use policy.

The task did not run an external search, did not inspect generated run folders, did not modify the frozen S2 model, and did not add DA, settlement, revenue, route-optimisation, stochastic, CVaR, mFRR, tariff, or gross-ETS logic.

All rows and conclusions remain caveated assumptions or blocked rows. No row is a Tata-exact fact, empirical validation claim, approved input-table row, or generated-run source.

## S3.0c-d2 Policy Application

S3.0c-d2 applied:

- `docs/optimisation/steel/S3/STEEL_S3_EVIDENCE_USE_AND_THESIS_ASSUMPTION_POLICY.md`
- `s3_evidence_use_tier_vocabulary.csv`
- `s3_model_input_use_status_vocabulary.csv`
- `s3_thesis_assumption_acceptance_policy.csv`
- `s3_material_parameter_sensitivity_mandate.csv`

Under that policy, an Athanasiadis public thesis table may be used as Tier B `public_secondary_literature_derived` evidence only when the immediate public source is source-carded and the relevant page, table, or section locator is complete.

The corrective pass therefore did not reject the Athanasiadis/Ren-style DRP/EAF values on evidence-tier grounds. It kept them blocked because the local/public source table was still not available through a complete locator.

## Source-Card Result

The targeted source lookup found an existing non-canonical source-card file:

- `data/03_Optimisation/inputs/assets/steel/source_cards/F18_athanasiadis_tata_ijmuiden_thesis.md`

That card identifies:

- title: `Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site`
- author: `Ioannis Athanasiadis; TU Delft`
- year: `2025`
- local reference: `Master_Thesis_Report_Athanasiadis (1).pdf`
- locator caveat: repo-local file not found in the prior scan
- modelling role: governance precedent, not a numerical input source

S3.0c-d1 added a canonical source-card row:

- `STEEL-SC-0021`

The row is intentionally blocked for numerical use:

- `locator_complete=false`
- `eligible_for_candidate_evidence=false`
- `eligible_for_dev_input_review=false`
- `source_review_status=locator_incomplete_not_numerical_source`

No DRP/EAF coefficient may be selected from this source until the source table is available through a stable public or repo-local locator with page, section, or table reference. If that locator is later supplied, the rows may be treated as Tier B candidate evidence with `tata_exact_claim_allowed=false`, `thesis_validation_claim_eligible=false`, and sensitivity review for material DRP/EAF coefficients.

## Candidate Evidence Result

No candidate-evidence rows were added for the prompt-listed Athanasiadis/Ren-style point values because the local/public table could not be verified.

The following values therefore remain uncanonicalised:

- EAF capacity: `400 t_DRI/hour`
- EAF DRI-to-crude-steel efficiency: `0.95`
- EAF electricity consumption: `0.5 MWh/t_DRI`
- EAF scrap consumption: `0.2 t_scrap/t_DRI`
- EAF oxygen consumption: `0.05 t_O2/t_DRI`
- EAF operation range: `0.9-1.1` of average capacity
- NG-DRP capacity: `500 t_pellets/hour`
- NG-DRP pellets-to-DRI efficiency: `0.74`
- NG-DRP electricity consumption: `0.1 MWh/t_pellets`
- NG-DRP natural-gas consumption: `195 m3_NG/t_pellets`
- NG-DRP direct CO2 emissions: `0.5 t_CO2/t_pellets`
- NG-DRP oxygen consumption: `0.1 t_O2/t_pellets`
- NG-DRP operation range: `0.7-1.1` of average capacity
- NG-DRP ramp rate: `0.1` of average capacity per hour

These values are not rejected technically. They remain Tier X blocked only because the controlling source-evidence layer does not yet contain a complete locator for the table.

## Selected Inputs

No new DRP/EAF energy inputs were selected.

The C1 energy-input table remains blocked for:

- `drp_natural_gas_demand`
- `drp_electricity_demand`
- `eaf_electricity_demand`
- `drp_eaf_output_conversion_basis`
- `c1_site_electricity_demand_proxy`

The existing selected C1 rows remain limited to:

- user-selected same-output route-share scenario rows
- route-share-scaled C0 coking proxy policy

No selected row is thesis-usable as an empirical fact or approved model input. Under the revised policy, future selected Tier B rows could become `thesis_model_assumption` or `thesis_model_sensitivity` rows only after locator, unit, basis, limitation, caveat, and sensitivity requirements are satisfied.

## Conversion Logic

The route-output conversion chain remains defined but not executable:

```text
dri_required_per_t_steel = 1 / eaf_dri_to_crude_steel_efficiency
pellets_required_per_t_steel = dri_required_per_t_steel / ng_drp_pellets_to_dri_efficiency
eaf_electricity_per_t_steel = dri_required_per_t_steel * eaf_electricity_per_t_dri
drp_electricity_per_t_steel = pellets_required_per_t_steel * drp_electricity_per_t_pellets
drp_natural_gas_per_t_steel = pellets_required_per_t_steel * drp_natural_gas_per_t_pellets
scrap_per_t_steel = dri_required_per_t_steel * scrap_per_t_dri
```

No pellets, DRI, crude-steel, liquid-steel, scrap, or HRC bases were silently equated.

## C1 Profile And Diagnostic Status

The three existing C1 profiles remain same-output route/material/WAG-driver profiles:

- `c1_high_drp_eaf_same_output_profile_24h_dev.csv`
- `c1_central_same_output_profile_24h_dev.csv`
- `c1_low_drp_eaf_same_output_profile_24h_dev.csv`

They were not regenerated with DRP/EAF component-energy rows because no selected DRP/EAF coefficients exist.

Allowed diagnostic level remains:

- `wag_generation_only`

Blocked diagnostic levels:

- `component_energy_boundary_diagnostic`
- `full_c1_plant_diagnostic`

## Interpretation

The C1 scenarios still demonstrate the structural WAG implication of the route policy:

- higher DRP-EAF share reduces retained BF activity;
- retained BF activity reduces BFG generation;
- retained BOF activity reduces BOFG generation;
- retained coking proxy activity reduces COG generation.

The C1 natural-gas and electricity exposure cannot yet be quantified because the DRP/EAF coefficient layer remains blocked.

No component grid import, potential C1 import offset, DRP natural-gas demand, DRP electricity demand, EAF electricity demand, complete emissions, gross ETS cost, revenue, or profit is reported.

## Remaining Work

Before C1 component diagnostics can run, add a complete source locator for a public DRP/EAF coefficient table and then create candidate-evidence rows for:

- `ng_drp_natural_gas_consumption`
- `ng_drp_electricity_consumption`
- `ng_drp_pellets_to_dri_efficiency`
- `eaf_electricity_consumption`
- `eaf_dri_to_crude_steel_efficiency`
- `eaf_scrap_consumption`

Only after those rows are present and selected under the S3 evidence-use policy should the C1 profiles be regenerated with DRP/EAF energy rows and component diagnostics be run.

## S3.0c-d3 Human-Verified Locator Correction

S3.0c-d3 supersedes the blocked d1/d2 source-locator result for the EAF and NG-DRP parameter tables. It uses a human-verified locator packet supplied after the earlier blocked run. No web search, broad repository discovery, generated run folder, S2 modification, DA logic, route optimisation, revenue, settlement, gross ETS, or market logic was introduced.

Immediate public source:

- `STEEL-SC-0021`: Ioannis Athanasiadis, *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site*, Delft University of Technology, February 17 2025.
- Evidence tier: Tier B `public_secondary_literature_derived`.
- Caveat: public-thesis/literature-derived assumptions, not Tata-exact operating data and not validation truth.

Human-verified locators:

- EAF: Section `3.5.4 Components of the new configurations`; subsection `Electric Arc Furnace (EAF)`; Figure 46; Table 1; page 56.
- NG-DRP: Section `3.5.4 Components of the new configurations`; subsection `Direct Reducing Plants (DRPs) / Natural Gas DRP`; Figure 47; Table 2; page 57.

`STEEL-SC-0021` is now locator-complete for these two tables. Candidate evidence rows `STEEL-WAG-EVID-0058` through `STEEL-WAG-EVID-0071` record the source values with original units and bases. The companion review file `s3_c1_drp_eaf_tier_b_evidence_review.csv` records Tier B status, sensitivity requirement, `tata_exact_claim_allowed=false`, and `thesis_validation_claim_eligible=false`.

## S3.0c-d3 Selected Inputs

Selected C1 route-energy inputs:

- `ng_drp_natural_gas_consumption = 195 m3_NG/t_pellets`
- `ng_drp_electricity_consumption = 0.1 MWh/t_pellets`
- `ng_drp_pellets_to_dri_efficiency = 0.74 t_DRI/t_pellets`
- `ng_drp_direct_co2_factor = 0.5 t_CO2/t_pellets`
- `eaf_electricity_consumption = 0.5 MWh/t_DRI`
- `eaf_dri_to_crude_steel_efficiency = 0.95 t_crude_steel/t_DRI`
- `eaf_scrap_consumption = 0.2 t_scrap/t_DRI`
- optional oxygen context: `eaf_oxygen_consumption = 0.05 t_O2/t_DRI`, `ng_drp_oxygen_consumption = 0.1 t_O2/t_pellets`

All selected rows remain caveated assumptions/sensitivities. None are Tata-exact, validation-claim eligible, or approved empirical truth.

## Derived Route-Output Basis

The C1 scenario route output is treated as a liquid/crude-steel proxy for this S3 component diagnostic only.

- `dri_required_per_t_steel = 1.0526315789 t_DRI/t_steel`
- `pellets_required_per_t_steel = 1.4224751067 t_pellets/t_steel`
- `eaf_electricity_per_t_steel = 0.5263157895 MWh/t_steel`
- `drp_electricity_per_t_steel = 0.1422475107 MWh/t_steel`
- `drp_natural_gas_per_t_steel = 277.3826458037 m3_NG/t_steel`
- `scrap_per_t_steel = 0.2105263158 t_scrap/t_steel`
- `drp_direct_co2_proxy_per_t_steel = 0.7112375533 t_CO2/t_steel`

No silent conversion to HRC, slab, or product basis is made.

## Component Diagnostic Results

The three same-output C1 profiles were regenerated with DRP/EAF component-energy rows. Route shares and total output are unchanged.

Diagnostic level for all three scenarios: `component_energy_boundary_diagnostic`.

| scenario | DRP-EAF share | DRP natural gas (m3) | component electricity before WAG offset (MWh) | potential WAG offset (MWh) | residual component grid import (MWh) |
|---|---:|---:|---:|---:|---:|
| `c1_high_drp_eaf` | 0.45 | 1017385.3831 | 2452.1596 | 2452.1596 | 0.0000 |
| `c1_central` | 0.39 | 881733.9987 | 2125.2050 | 2125.2050 | 0.0000 |
| `c1_low_drp_eaf` | 0.32 | 723474.0502 | 1743.7580 | 1743.7580 | 0.0000 |

The zero residual component grid import is not a plant-level import result. It occurs inside the component-only electricity boundary, while downstream, auxiliary, full heat/steam, and complete electricity boundaries remain incomplete.

## S3.0c-d3 Interpretation

At the same output basis, higher DRP-EAF share reduces retained BF/coking WAG generation and increases external natural-gas and electricity exposure. C1 WAG generation is structural from retained BF, BOF, and coking drivers; no flat C0 WAG credit is used.

Cost integration, DA logic, gross ETS, complete site emissions, and actual dispatch interpretation remain blocked.
