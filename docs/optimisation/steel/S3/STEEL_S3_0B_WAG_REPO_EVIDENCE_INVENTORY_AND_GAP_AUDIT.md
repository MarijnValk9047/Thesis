# S3.0b-a2 WAG Repo Evidence Inventory and Gap Audit

Status: governance evidence audit only  
Stage: S3.0b-a2  
Model marker: GPT-5.5  
Reasoning marker: high  
Thesis usability: false  

This memo inventories the bounded repository evidence available for a future S3.0b-b fixed-profile WAG diagnostic. It does not approve values, create executable input tables, implement calculations, or promote any source to thesis-grade model input.

## Scope and Search Boundary

Requested research memo path `docs/optimisation/steel/research_memo/` was not present. The allowed targeted lookup found:

- `docs/optimisation/steel/research_memos/`

The audit searched only:

- `docs/optimisation/steel/research_memos/`
- direct markdown files immediately under `docs/optimisation/steel/`
- `docs/optimisation/steel/S2/STEEL_S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT.md`
- `docs/optimisation/steel/S3/STEEL_S3_ENERGY_COST_EMISSIONS_ACCOUNTING_DESIGN.md`
- `docs/optimisation/steel/S3/STEEL_S3_0B_FIXED_PROFILE_WAG_DIAGNOSTIC_INPUT_AND_CONTRACT.md`
- `docs/optimisation/steel/STEEL_S2_S3_DOWNSTREAM_AND_WAG_BOUNDARY_CORRECTION.md`
- `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_0b_wag_coefficient_requirement_register.csv`
- `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_0b_wag_diagnostic_calculation_contract.csv`
- `data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_0b_fixed_profile_wag_diagnostic_contract.csv`
- `data/03_Optimisation/inputs/assets/steel/S2/s2_candidate_review/s3_wag_accounting_boundary_register.csv`
- `data/03_Optimisation/inputs/assets/steel/S2/s2_candidate_review/s3_wag_allocation_mode_register.csv`

Direct markdown files searched under `docs/optimisation/steel/` were:

- `README.md`
- `STEEL_ASSUMPTION_REGISTER.md`
- `STEEL_CONFIGURATION_SCOPE_FREEZE.md`
- `STEEL_DATA_AND_PARAMETER_PLAN.md`
- `STEEL_IMPLEMENTATION_FREEZE_V1.md`
- `STEEL_IMPLEMENTATION_ROADMAP.md`
- `STEEL_MODEL_BLUEPRINT.md`
- `STEEL_MODEL_POLICY_DECISIONS.md`
- `STEEL_PARAMETER_UNIVERSE.md`
- `STEEL_RESEARCH_WAVE_TRACKER.md`
- `STEEL_S2_S3_DOWNSTREAM_AND_WAG_BOUNDARY_CORRECTION.md`
- `STEEL_STAGE_GATE_VALIDATION_PLAN.md`
- `STEEL_THESIS_WRITING_PLAN.md`
- `STEEL_TRACTABILITY_AND_CHANGE_CONTROL.md`
- `STEEL_VALIDATION_AND_TRACTABILITY_PLAN.md`

Research memo files searched were:

- `deepsearch_1_steel_milp_parameter_categories.md`
- `deepsearch_2_tata_ijmuiden_topology_validation_targets.md`
- `deepsearch_3_technology_ranges_annual_to_hourly.md`
- `deepsearch_4_wags_internal_energy_emissions.md`
- `deepsearch_5_financial_ets_tariffs_market_parameters.md`
- `deepsearch_6_additional_assumptions.md`
- `DEEPSEARCH_F_SOURCE_APPENDIX.md`
- `README.md`

Not searched:

- whole repository
- PDFs
- generated run folders
- notebook outputs
- web or external sources
- unrestricted `data/` or `scripts/` trees

Generated run folders are not canonical source artifacts for S3.0b-b.

## Evidence Inventory

| evidence_id | source_path | source_section_or_heading | source_type | wag_carrier | evidence_category | parameter_or_model_object | unit_if_present | time_basis_if_present | configuration_relevance | can_support_s3_0b_b | human_review_needed | risk_if_used_directly | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E01 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | Executive finding and modelling consequences | research memo | BFG, COG, BOFG/LD gas | structural evidence | carrier-specific WAG layer tied to S2 throughput | not specified | hourly model implied, not sourced | both | partial_context_only | yes | Treating structure as approved coefficients | Supports WAG layer design, not executable values. |
| E02 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | WAG/internal energy topology table | research memo | BFG | structural evidence | BF-linked BFG producer and consumers | not specified | not specified | both | partial_context_only | yes | Missing Tata holder and pressure data | BF/BFG topology is strong, but no reviewed numeric coefficient. |
| E03 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | WAG/internal energy topology table | research memo | COG | structural evidence | coking-route COG accounting candidate | not specified | not specified | both | partial_context_only | yes | Coking closure effects can be misrepresented | Relevant to retained or changing coking backbone, not active flexible coking. |
| E04 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | WAG/internal energy topology table | research memo | BOFG/LD gas | structural evidence | BOF/LD gas producer and oxygas holder | not specified | not specified | both | partial_context_only | yes | Holder existence could be mistaken for known capacity | Oxygas holder existence is useful; capacity remains unavailable. |
| E05 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | WAG/internal energy topology table and postponed items | research memo | mixed gas | blocked/confidential/redacted | detailed mixed-gas optimisation | not specified | not specified | future-only | no_blocked | yes | False precision from guessed mixed-gas setpoints | Detailed mixed-gas setpoints and optimisation are deferred. |
| E06 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | WAG/internal energy topology table | research memo | generic WAG | structural evidence | natural-gas backup and displacement interface | not specified | not specified | both | partial_context_only | yes | Treating displacement as automatic one-for-one substitution | Supports displacement concept, not conversion coefficient. |
| E07 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | Recommended minimal S3 parameter set | research memo | generic WAG | validation target | residual-gas power scale and Vattenfall/on-site generation interface | approximately 2.0 TWh/yr noted as validation scale | annual validation only | both | no_validation_only | yes | Annual anchor used as hourly truth | Useful for plausibility checks only. |
| E08 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | WAG/internal energy topology table | research memo | generic WAG | partial context only | steam and boiler consumers | not specified | not specified | both | partial_context_only | yes | Overbuilding detailed steam network from sparse evidence | Supports inclusion as accounting sink, not detailed dispatch. |
| E09 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | Recommended minimal S3 parameter set | research memo | BFG, COG, BOFG/LD gas | candidate numerical evidence | gas generation coefficients by activity | per t HM, per t coke or coal, per t liquid steel | not specified | both | yes_candidate | yes | Public generic ranges treated as Tata exact values | Identifies needed coefficient families, but the memo does not provide reviewed executable values. |
| E10 | `docs/optimisation/steel/research_memos/deepsearch_1_steel_milp_parameter_categories.md` | Parameter universe table | research memo | BFG, COG, BOFG/LD gas | candidate numerical evidence | gas generation and gas quality families | Nm3/t, GJ/t, MJ/Nm3, vol-% | not specified | both | yes_candidate | yes | Units and source tier may be mixed without review | Provides parameter classes and unit families, not approved rows. |
| E11 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | Recommended minimal S3 parameter set and red flags | research memo | generic WAG | structural evidence | flare/spill residual sink | not specified | hourly balance implied | both | partial_context_only | yes | Zero-cost disposal or missing residual balance | Supports mandatory residual accounting, not penalty magnitude. |
| E12 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | Emissions accounting section | research memo | generic WAG | structural evidence | no-double-counting emissions boundary | not specified | not specified | both | partial_context_only | yes | Counting same carbon at generation and combustion/flare | Boundary rule is clear; factors need review. |
| E13 | `docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md` | Recommended minimal S3 parameter set | research memo | generic WAG | sensitivity-only | WAG emissions factors, NG factor, captured CO2 visibility | not specified | not specified | both | partial_context_only | yes | Sensitivity values mistaken for approved ETS accounting | Supports future sensitivity and visibility classes only. |
| E14 | `docs/optimisation/steel/STEEL_ASSUMPTION_REGISTER.md` | WAG assumptions | governance doc | generic WAG | assumption | useful-energy substitution and NG replacement value path | not applicable | not applicable | both | partial_context_only | yes | Treating WAG as free revenue or direct electricity value | Strong governance support for bounded valuation logic. |
| E15 | `docs/optimisation/steel/STEEL_ASSUMPTION_REGISTER.md` | Confidential transfer price and direct valuation assumptions | governance doc | generic WAG | blocked/confidential/redacted | internal transfer prices and direct electricity-price valuation | not applicable | not applicable | both | no_blocked | yes | Unreviewed monetisation or confidential value substitution | Keeps WAG revenue and direct electricity valuation blocked. |
| E16 | `docs/optimisation/steel/STEEL_PARAMETER_UNIVERSE.md` | Wave D WAG/internal energy summary | governance doc | BFG, COG, BOFG/LD gas | structural evidence | semi-detailed WAG layer and postponed full dispatch | not specified | not specified | both | partial_context_only | yes | Reopening market or dispatch logic too early | Confirms B-lite approach and deferred DA/stochastic/CVaR/mFRR. |
| E17 | `docs/optimisation/steel/research_memos/deepsearch_2_tata_ijmuiden_topology_validation_targets.md` | Topology and validation targets | research memo | BFG, COG, BOFG/LD gas | validation target | Phase 1 effect on WAG availability | public annual/topology anchors | annual/contextual | C1 | no_validation_only | yes | Public transition anchors used as hourly WAG truth | Supports expected WAG scarcity direction, not coefficients. |
| E18 | `docs/optimisation/steel/STEEL_VALIDATION_AND_TRACTABILITY_PLAN.md` | Future S3 WAG validation checks | governance doc | BFG, COG, BOFG/LD gas | validation target | WAG balance closure and plausibility checks | not specified | hourly balance implied | both | no_validation_only | yes | Validation checks mistaken for source data | Useful acceptance logic for later diagnostic. |
| E19 | `data/03_Optimisation/inputs/assets/steel/S2/s2_candidate_review/s3_wag_accounting_boundary_register.csv` | WAG accounting boundary rows | governed register | BFG, COG, BOFG/LD gas, generic WAG | structural evidence | WAG producers, consumers, interface, sinks | not applicable | not applicable | both | partial_context_only | yes | Register row treated as numeric input | Confirms objects and blocked revenue status only. |
| E20 | `data/03_Optimisation/inputs/assets/steel/S2/s2_candidate_review/s3_wag_allocation_mode_register.csv` | WAG allocation modes | governed register | generic WAG | structural evidence | allowed and blocked allocation modes | not applicable | not applicable | both | partial_context_only | yes | Unconstrained arbitrage or export revenue | Blocks export revenue, direct price valuation, and unconstrained WAG arbitrage. |

## Gap Matrix

| required_area | evidence_status | main_evidence | blocks_s3_0b_b_implementation | gap_or_limitation |
|---|---|---|---|---|
| BFG generation linked to BF activity | candidate_numerical_evidence_found | E02, E09, E10 | yes, for coefficient execution | Public generic coefficient family is identified, but no reviewed numeric range is captured as executable input. |
| BOFG/LD gas generation linked to BOF activity | candidate_numerical_evidence_found | E04, E09, E10 | yes, for coefficient execution | BOF/LD family and holder existence are present; reviewed yield and energy-content values are missing. |
| COG generation linked to coking-route accounting candidate | candidate_numerical_evidence_found | E03, E09, E10, E17 | yes, for coefficient execution | COG family exists, but coking-route activity basis and closure effects need reviewed treatment. |
| WAG lower heating value or energy-content ranges | external_deepsearch_needed | E10 | yes | Unit families are named, but exact candidate ranges and source traceability are not available in the allowed corpus. |
| WAG process-fuel substitution | partial_context_only | E06, E14, E20 | yes, for quantitative substitution | Substitution concept is governed; conversion factors and priority rules are not reviewed. |
| WAG steam/boiler use | partial_context_only | E08, E20 | yes, for quantitative use | Steam/boiler sink is structurally justified; efficiency and unit basis are missing. |
| WAG-to-power interface efficiency | partial_context_only | E07, E16, E19 | yes | Vattenfall/on-site generation interface is governed, but efficiency values are not available. |
| WAG-to-power interface capacity or limit | blocked_confidential_or_redacted | E04, E05, E07 | yes | Specific VN24/VN25/IJ01 limits, dispatch detail, and holder capacities are not public in the allowed corpus. |
| Vattenfall/VN24/VN25/IJ01 interface treatment | covered_structurally | E07, E15, E16, E19 | no, if kept as non-dispatch interface | Full Vattenfall dispatch remains blocked; only aggregate interface treatment is supported. |
| flare/spill/unused WAG treatment | covered_structurally | E11, E18, E19, E20 | no, for structure; yes, for penalty magnitude | Residual sink is required; flare/spill penalty or cost convention remains unresolved. |
| WAG combustion/flare emissions factor | external_deepsearch_needed | E12, E13 | yes | Boundary rule exists; reviewed emissions factors or derivation convention are missing. |
| natural-gas displacement factor | partial_context_only | E06, E13, E14 | yes | NG replacement concept exists; displacement factor and unit convention need review. |
| net-electricity-import offset convention | covered_structurally | E07, E20 | no, if diagnostic-only | Offset may be diagnostic only; efficiency/capacity gaps limit quantitative use. |
| captured CO2 visibility convention | validation_only | E13, E17 | no, if reporting-only | Captured CO2 is visible as context, not as WAG executable coefficient. |
| no-double-counting emissions boundary | covered_structurally | E12, E18 | no | Rule is structurally clear; factors still require review. |
| C1 effect on WAG availability when BF/coking backbone changes | validation_only | E03, E17 | yes, for quantified C1 comparison | Directional effect is supported; quantified WAG availability change needs reviewed coefficients and activity profiles. |
| blocked WAG revenue, direct price valuation, arbitrage, full Vattenfall dispatch, mixed-gas optimisation | covered_structurally | E05, E14, E15, E16, E20 | no, because these must remain blocked | These are well-governed blocks; they are not implementation inputs. |

## Implementation-Readiness Conclusion

S3.0b-b should not start as a calculating WAG diagnostic yet. The allowed corpus is strong enough for structural design, object classification, blocked-mode governance, and validation framing, but it is not sufficient for a coefficient-executing fixed-profile diagnostic.

The current repository evidence supports:

- carrier-specific WAG structure for BFG, COG, and BOFG/LD gas;
- WAG producers, consumers, WAG-to-power interface, and flare/spill sink classes;
- useful-energy substitution as the only bounded value logic;
- Vattenfall/on-site generation as an interface, not a dispatch plant;
- residual flare/spill accounting;
- emissions boundary separation and no-double-counting rules;
- validation-only annual/contextual anchors.

The current repository evidence does not yet support executable S3.0b-b calculations because reviewed candidate numeric evidence is still missing or incomplete for:

- BFG, COG, and BOFG/LD generation coefficients with units and activity basis;
- lower heating value or energy-content ranges;
- WAG-to-power conversion/interface efficiency;
- WAG-to-power interface capacity or bounded proxy;
- steam/boiler conversion factors;
- WAG combustion/flare emissions factors or derivation convention;
- natural-gas displacement factor;
- flare/spill penalty or diagnostic treatment magnitude;
- quantified C1 WAG availability impact after BF/coking backbone changes.

S3.0b-b may start only as a non-calculating implementation scaffold or validator shell if explicitly requested. It should not compute WAG generation, allocation, net-import offsets, substitution, or emissions until the missing coefficient classes are filled through reviewed candidate/provisional inputs.

## Deepsearch Recommendation

Recommendation: yes, targeted external deepsearch is needed before coefficient-executing S3.0b-b implementation.

Targeted external questions:

1. What public BREF, worldsteel, or peer-reviewed ranges give BFG generation per tonne hot metal, COG generation per tonne coke or coal, and BOFG/LD gas generation per tonne liquid steel, with units and source basis?
2. What public ranges give LHV or energy-content values for BFG, COG, and BOFG/LD gas, including unit conversions between Nm3, GJ, and MWh?
3. Are public values available for Tata IJmuiden Vattenfall/VN24/VN25/IJ01 residual-gas generation interface capacities or efficiencies? If not, what generic steelworks conversion-efficiency proxy is defensible?
4. What public boiler or steam-use efficiency ranges are defensible for WAG use in integrated steelworks accounting?
5. What EU ETS, MRV, worldsteel, or BREF guidance supports WAG combustion and flare emissions accounting without double counting carbon at both generation and combustion?
6. What convention is defensible for natural-gas displacement by WAG useful-energy substitution, including unit basis and emissions treatment?
7. What public evidence can quantify the Phase 1 reduction in BFG/COG/BOFG availability after BF7 and KGF2 closure without using confidential Tata operational data?

## Red Flags

- WAG electricity must not be treated as free export revenue.
- WAG allocation must not become unconstrained arbitrage.
- Generated run folders must not become canonical source artifacts.
- Public annual anchors must not be used as executable hourly truth.
- Redacted or confidential values must not be treated as exact Tata inputs.
- Full Vattenfall dispatch must remain blocked until deterministic S3 accounting is stable and separately governed.
- Mixed-gas optimisation must remain deferred until setpoints, capacities, and evidence are reviewed.
- Validation targets must not be promoted into coefficients.

## Final Audit Status

The repository contains enough WAG evidence for structural governance and targeted source planning. It does not yet contain enough reviewed numerical evidence to implement an executable fixed-profile WAG diagnostic in S3.0b-b.

