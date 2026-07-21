# WAG Carriers and CO2 Factor Source Card

Status: source-card repair memo, development-only.

Thesis usability: false.

This memo records governed evidence status for waste-gas carrier composition,
lower heating value and CO2 factor repair work in the public Tata Steel
IJmuiden-inspired C0/C1 physical/accounting model. It is not an executable input
table, not Tata operating truth, and not a source of DA revenue, ETS objective
terms, generator export value, or hidden residual calibration.

## Scope and abstraction level

Waste-gas carriers remain separate in the C5 baseline:

- BFG from the blast-furnace/hot-stove boundary;
- COG from the coking/KGF boundary after coking self-use;
- BOFG/oxygas from the BOF/OSF boundary;
- mixed gas only where explicitly governed by a later gas-network policy.

The current C5 policy is to use carrier-specific balances and visible
flare/spill/residual diagnostics. WAG holders are not hourly stores, WAG is not
directly valued in DA markets, and WAG carbon must be counted once.

## Status vocabulary

Use these labels for future rows:

- `direct_public_anchor`
- `source_backed_candidate`
- `derived_candidate`
- `generic_range`
- `modelling_precedent_only`
- `governed_assumption`
- `context_only`
- `sensitivity_only`
- `not_found`

Recommended model-use labels:

- `validation_target`
- `development_input_candidate`
- `sensitivity_range`
- `residual_policy_candidate`
- `source_card_repair_needed`
- `deferred`

## 2026 source repair update - Cavaliere WAG composition and LHV status

Cavaliere (2019) is a useful route-level and WAG-composition repair source, but
the original book/table was not locally inspected in this repository during
this markdown repair. Numeric Table 1.3 composition and LHV rows are therefore
not entered as active parameters here. They remain source-card repair TODOs
until the table is directly verified.

| Parameter ID | Value / range | Unit | Original basis | Converted basis / derivation | Status label | Recommended model use | Source title, authors/organisation, year, URL/DOI | Locator status | Caveat |
|---|---|---|---|---|---|---|---|---|---|
| `CAVALIERE_TABLE_1_3_WAG_LHV_COMPOSITION_REPAIR` | not_entered | n/a | Table 1.3 reportedly gives volumetric flow rates, LHVs and compositions of cleaned steelwork off-gases for a modern 6 Mt/y steel plant | n/a | not_found | source_card_repair_needed / deferred | Pasquale Cavaliere (2019), *Clean Ironmaking and Steelmaking Processes: Efficient Technologies for Greenhouse Emissions Abatement*, Springer, https://doi.org/10.1007/978-3-030-21209-4 | source_locator_not_verified_in_repo | Do not add WAG composition or LHV rows from OCR-ambiguous or uninspected tables; value_from_reviewed_research_note_not_locally_verified. |
| `CAVALIERE_ROUTE_ENERGY_CONTEXT` | context_only | qualitative | Table 1.4 and route-level energy context reportedly discuss BF, BOF and EAF route consumption | n/a | context_only | validation_target / deferred | Cavaliere (2019), DOI above | source_locator_not_verified_in_repo | Route-level context only; not a Tata plant-level electricity/NG residual input. |
| `CAVALIERE_INTEGRATED_MILL_CO2_FLOW_CONTEXT` | context_only | qualitative | Figure 1.13 reportedly illustrates CO2 flows in an integrated steel mill | n/a | context_only | validation_target / deferred | Cavaliere (2019), DOI above | source_locator_not_verified_in_repo | Illustration/context only; do not use as a consolidated CO2 counter. |

Values from the reviewed research note to verify before any future numeric row
is created include COG, BFG, BOFG and mixed-gas LHV and composition entries.
They must not be promoted until Table 1.3 is directly checked.

## 2026 source repair update - WAG point-of-oxidation CO2 factors

The prior S3 source-evidence and selected-development-input registers already
contain a consistent, primary-source-backed factor set from the Netherlands
fuel list (January 2025). This card adopts that evidence for a **development-
only, partial, point-of-oxidation WAG ledger**. The values are national
reporting factors, not measured Tata gas compositions and not a basis for a
consolidated site total, ETS cost, or thesis claim of plant-exact emissions.

This repairs the earlier `not_found` status in this card without creating new
executable process inputs.

| Parameter ID | Value / range | Unit | Original basis | Converted basis / derivation | Status label | Recommended model use | Source title, authors/organisation, year, URL/DOI | Locator status | Caveat |
|---|---|---|---|---|---|---|---|---|---|
| `WAG_POINT_OF_OXIDATION_CO2_SOURCE` | RVO Netherlands fuel list January 2025 | kgCO2/GJ | Official Netherlands fuel list, Section 1 fuel table | Source-card register `STEEL-SC-0011`; evidence rows `STEEL-WAG-EVID-0025` to `0027` | direct_public_anchor | development-only combustion/flaring ledger | Netherlands Enterprise Agency RVO, *The Netherlands list of fuels and standard CO2 emission factors*, January 2025 | Section 1 fuel list table; source-register locator | National reporting factor; not plant-specific gas composition. |
| `COG_CO2_FACTOR_NETHERLANDS` | 42.8 | kgCO2/GJ | Direct combustion factor | NCV/LHV energy basis | source_backed_candidate | development-only WAG oxidation or flare accounting | RVO, January 2025; `STEEL-WAG-EVID-0025` | Section 1 fuel list table | Use only at represented combustion or flare sink; not at COG generation. |
| `BFG_CO2_FACTOR_NETHERLANDS` | 247.4 | kgCO2/GJ | Direct combustion factor | NCV/LHV energy basis | source_backed_candidate | development-only WAG oxidation or flare accounting | RVO, January 2025; `STEEL-WAG-EVID-0026` | Section 1 fuel list table | Use only at represented combustion or flare sink; not at BFG generation. |
| `BOFG_CO2_FACTOR_NETHERLANDS` | 191.9 | kgCO2/GJ | Direct combustion factor | NCV/LHV energy basis | source_backed_candidate | development-only WAG oxidation or flare accounting | RVO, January 2025; `STEEL-WAG-EVID-0027` | Section 1 fuel list table | BOFG/LDG terminology mapping remains explicit; use only at represented sink. |
| `NATURAL_GAS_CO2_FACTOR_REFERENCE` | 56.1 | kgCO2/GJ | EU ETS/FAR reference factor | NCV/LHV energy basis | source_backed_candidate | separate explicit-NG-combustion mode only | `STEEL-WAG-EVID-0034` / existing S3 selection | Existing source-evidence locator | Do not apply to unallocated residual NG; this is not a WAG factor. |

## WAG carbon-boundary policy

Use either aggregate process CO2 counters or WAG-explicit combustion accounting
for a given carbon-bearing route. The active C5 WAG mode is **point of
oxidation**: count WAG carbon once at represented boiler, generator, process or
flare sinks; do not count the same carbon at BFG/COG/BOFG generation.

The WAG-explicit ledger is deliberately partial. It excludes unallocated NG,
residual electricity, Scope 2, unrepresented site fuel use and aggregate
process counters. Residuals remain visible boundary KPIs; they are not filled
or allocated merely to close an anchor.

This policy is especially important for:

- BF/BFG;
- KGF/COG;
- BOF/BOFG;
- boilers K15/K16, K23/K24 and K41;
- STEG11, TG2 and IJ01/VN25 generator diagnostics;
- BF hot stoves;
- HSM/WBW reheating;
- WAG flare/spill diagnostics.

## Frozen scope decisions for the C5 WAG layer

- No fixed WAG/NG ratios are invented. For an existing, eligible controller,
  carrier-specific WAG is used first; explicitly modelled NG may cover only
  the remaining controller demand. This does not allocate site residual NG.
- Wobbe-index, gas-quality and quantitative mixed-gas constraints are outside
  the current thesis scope. `mixed_wag` remains a structural/reporting label,
  never a physical fuel carrier.
- Residual NG and electricity are tracked with their sign and provenance. They
  are not converted into loads, filled, dispatched, allocated to plants or
  used to calibrate other parameters.

| Parameter ID | Value / range | Unit | Original basis | Converted basis / derivation | Status label | Recommended model use | Source title, authors/organisation, year, URL/DOI | Locator status | Caveat |
|---|---|---|---|---|---|---|---|---|---|
| `WAG_CARBON_COUNTING_POLICY` | count_carbon_once | policy | Project CO2/WAG boundary governance | n/a | governed_assumption | residual_policy_candidate / deferred | Project C5p_h diagnostics and steel model governance, 2026 | not_applicable | Required before any consolidated CO2 total or ETS-ready claim. |
| `DIRECT_WAG_MARKET_VALUE_ALLOWED` | false | bool | Project WAG/economics policy | n/a | governed_assumption | deferred | Project steel model governance, 2026 | not_applicable | WAG has value only through useful conversion or explicit internal offset; no direct WAG market value. |
| `WAG_HOLDERS_AS_HOURLY_STORES_BASE` | false | bool | C5p_d buffer/store register and WAG boundary diagnostics | n/a | governed_assumption | deferred | Project C5p_d/C5p_h diagnostics, 2026 | not_applicable | WAG holders are not hourly stores in the current C5 baseline. |

## Residual electricity and residual NG boundary policy

Residual/background electricity and residual/background natural gas are visible
diagnostic boundary terms only. They may reconcile full-site public anchors only
after all source-backed modelled plant loads, modelled gas uses and internal
generation offsets are accounted for.

They are not:

- executable plant parameters;
- dispatchable flexible loads;
- hidden calibration plugs;
- economics denominator fixes;
- DA price-taking assets;
- CO2 objective terms.

## 2026 source repair update - Gajdzik et al. 2025 route-level context

Gajdzik, Wolniak and Grebski (2025) is useful context for route-level BF-BOF
emissions/electricity/coke discussions in Poland. It is not a Tata IJmuiden
plant-level electricity, NG or residual-load source.

| Parameter ID | Value / range | Unit | Original basis | Converted basis / derivation | Status label | Recommended model use | Source title, authors/organisation, year, URL/DOI | Locator status | Caveat |
|---|---|---|---|---|---|---|---|---|---|
| `GAJDZIK_POLISH_BF_BOF_CONTEXT_STATUS` | context_only | qualitative | Polish BF-BOF econometric route-level context | n/a | context_only | validation_target / deferred | Gajdzik, Wolniak and Grebski (2025), *An Econometric Analysis of CO2 Emission Intensity in Poland's Blast Furnace-Basic Oxygen Furnace Steelmaking Process*, Sustainability 17(9), 4045, https://doi.org/10.3390/su17094045 | source_locator_not_verified_in_repo | Do not use Polish national BF-BOF GWh series to calibrate Tata residual/background electricity; do not use Polish BOF steel CO2 intensity as a Tata process counter. |

## Source notes

- Cavaliere (2019) should be revisited with direct table verification before
  any WAG LHV or composition values are added.
- Official fuel CO2 factors need a separate source-card repair with the
  original RVO/National source linked before they are used as project-canonical
  fuel-explicit factors.
- Consolidated CO2 remains component-diagnostic only until the WAG carbon
  boundary, energy boundary and residual electricity/NG policies are frozen.
