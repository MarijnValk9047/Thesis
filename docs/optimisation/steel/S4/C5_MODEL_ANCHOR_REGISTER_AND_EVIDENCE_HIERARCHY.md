# C5 Model Anchor Register and Evidence Hierarchy

## A. Purpose and Scope

This document is the current canonical C5 anchor register for validation,
reporting, residual KPI definition, and later sensitivity scoring in the
public Tata Steel IJmuiden-inspired steel MILP workstream.

It consolidates the anchor and evidence information that was previously split
across:

- `C5_ANNUAL_C0_C1_PHYSICAL_ACCOUNTING_RECONCILIATION.md`
- `c5_annual_anchor_reconciliation_matrix.csv`
- `C5_PRE_ECONOMICS_ALIGNMENT_GATE.md`
- `c5_anchor_acceptance_policy.csv`
- `STEEL_S3_EVIDENCE_USE_AND_THESIS_ASSUMPTION_POLICY.md`
- C5p_g residual electricity/NG diagnostics
- C5p_h CO2 and plant-energy anchor diagnostics
- C5p_i source-card candidate overlay diagnostics
- plant source cards under `data/03_Optimisation/inputs/assets/steel/source_cards/`
- compact C5 candidate registers and source-card-derived provenance artifacts

Older anchor files remain historical/source artifacts. This document and its
companion CSV are the current leading C5 anchor register for validation,
residual KPI reporting, denominator normalisation, and later anchor-scoring
design.

This is not an executable model-input table. It does not change model
equations, development inputs, source cards, constraints, objective terms, or
dispatch behaviour. Active model targets, validation anchors, source-card
candidates, and executable parameters remain separate.

Anchors may guide validation, residual KPI reporting, denominator
normalisation, and later sensitivity scoring. They must not be silently
converted into dispatch constraints or executable development inputs.

Companion files:

- `data/03_Optimisation/inputs/assets/steel/S4/c5_model_anchor_register/c5_model_anchor_evidence_register.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_model_anchor_register/c5_model_anchor_evidence_register_schema.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_model_anchor_register/summary.json`

The C5p_k patch intentionally did not inspect Athanasiadis, Badarinath, or MER
raw PDFs. Athanasiadis Table 8/9 rows are user-supplied model-precedent seeds
for this register. MER/Tata candidate anchors inherited from existing
source-card or candidate-register work are retained as open partial validation
or residual-KPI anchors rather than being blocked solely because this task did
not reopen the raw PDF.

## B. Source and Evidence Hierarchy

### Evidence Tiers

| Tier | Name | C5 interpretation |
|---|---|---|
| Tier A | `primary_public_site_specific` | Official Tata, MER, or formal public site-specific technical evidence. Can support Tata-exact public claims only when boundary, unit, locator, and denominator match. |
| Tier B | `public_secondary_literature_derived` | Public thesis, secondary literature, or site-inspired modelling precedent. Useful for modelling structure and candidate values, not exact Tata truth. |
| Tier C | `generic_technology_public` | Public generic process literature. Supports parameter ranges and sensitivities, not primary site anchors. |
| Tier D | `user_selected_scenario_policy` | Explicit project scenario choice. Can define what is being tested, not what real operation is. |
| Tier E | `derived_from_source_backed_inputs` | Derived values. They inherit the weakest input evidence tier and sensitivity obligation. |
| Tier F | `validation_target_only` | Public annual values and context anchors. Validation/reporting only, not hourly constraints or executable coefficients. |
| Tier X | `blocked` | Unverifiable, confidential/redacted without usable public locator, internally inconsistent, or missing. |

### C5 Source Trust Rank

| Rank | Meaning | Use |
|---|---|---|
| Rank 1 | Official Tata/MER/public technical site-specific documents, including MER Heracless and official Tata/MER reports. | Highest priority for physical/site-level anchors when boundary and denominator match. |
| Rank 2 | Official/public technical topology and production-volume documents. | Strong topology and production context, weaker for detailed coefficients if not given. |
| Rank 3 | Athanasiadis Tables 8/9 and related public-thesis model outputs. | High-value model-precedent anchors with denominator/unit caveats; not official Tata truth. |
| Rank 4 | Badarinath as secondary methodological and Tata-case abstraction precedent. | Important for methodology and abstraction, not strongest for site-level energy/CO2 anchors. |
| Rank 5 | Generic technology literature and source-card candidate values. | Parameter ranges and sensitivities only unless later reviewed. |
| Rank X | Blocked, unverifiable, missing, confidential/redacted, or inconsistent. | Do not use except to track missing evidence. |
| `internal_c5_diagnostic` | Current C5 diagnostic/register output. | Useful for current model status and residual KPI design, but it cannot outrank external evidence. |

MER and official Tata documents generally outrank Athanasiadis and Badarinath
for physical/site-level anchors. Athanasiadis Tables 8/9 remain valuable
model-precedent anchors, especially for electricity, NG, CO2, and WAG scale
checks, but they are not official Tata operating truth. Badarinath remains a
methodological and case-abstraction precedent. Generic literature supports
parameter ranges and sensitivity design.

## C. Anchor Categories

The companion register currently contains 52 seed rows:

| Category | Rows |
|---|---:|
| `active_model_target_anchors` | 1 |
| `blocked_or_deferred_anchor_context` | 2 |
| `co2_site_or_process_candidate_anchors` | 5 |
| `electricity_gross_use_anchors` | 9 |
| `final_product_downstream_proxy_anchors` | 7 |
| `grid_import_net_electricity_exposure_anchors` | 2 |
| `natural_gas_full_site_or_component_use_anchors` | 6 |
| `onsite_generation_wag_electricity_anchors` | 3 |
| `oxygen_and_utility_sanity_anchors` | 4 |
| `process_level_co2_candidate_anchors` | 3 |
| `production_and_denominator_anchors` | 2 |
| `wag_generation_and_availability_anchors` | 8 |

Conceptually, anchors are grouped as:

- production and denominator anchors;
- electricity gross-use anchors;
- grid import / net electricity exposure anchors;
- onsite generation / WAG-electricity anchors;
- natural gas full-site and component-use anchors;
- WAG generation and WAG availability anchors;
- CO2 site-level and process-level candidate anchors;
- final-product and downstream proxy anchors;
- oxygen and utility sanity anchors;
- active model target anchors;
- blocked or deferred anchors.

## D. Denominator and Scaling Policy

The active C5 physical/accounting target is `6.75 Mt/y`
liquid-steel-equivalent / active production proxy. Raw public anchors and
model-precedent anchors retain their original denominator beside any
active-scaled comparison.

Denominator concepts tracked in the register:

- liquid steel;
- crude steel;
- final product;
- hot rolled coil / HRC;
- rolled steel;
- site-level annual total;
- unknown denominator.

Scaling policy:

| Source denominator | Scaling factor | Allowed use |
|---|---:|---|
| C0/reference liquid-steel anchors from MER/public reference values | `6.75 / 7.2` | Use only where the anchor is linearly or approximately scalable. |
| C1/Heracless liquid-steel anchors | `6.75 / 6.8` | Use only where the anchor is linearly or approximately scalable. |
| Athanasiadis Table 8/9 denominator | `6.75 / 6.2` | Do not apply until the 6.2 Mt/y denominator is verified. |

Scaling classifications:

- `yes`: linear scaling is acceptable for the specific annual flow or production proxy.
- `approximate`: scaling is useful for comparison but not a physical proof.
- `no`: do not scale, usually because the value is a capacity, peak, duty-cycle, generator interaction, WAG availability interaction, or boundary total.
- `not_applicable`: no production denominator applies.

Peak demand, connection capacity, generator duty cycles, WAG/generator
interaction effects, and nonlinear process behaviour should not be blindly
linearly scaled. Raw, per-tonne, and scaled-to-6.75 values must be retained side
by side.

## E. Anchor Register Rules

The canonical CSV fields are defined in
`c5_model_anchor_evidence_register_schema.csv`. The key rules are:

- new anchors can be appended without changing existing IDs;
- obsolete anchors are superseded, not deleted;
- conflicts are recorded explicitly using `conflict_status`;
- active model targets and external validation anchors remain distinguishable;
- `model_use_status=executable_constraint` is reserved and should normally be absent from this governance register;
- `model_use_status=blocked` rows document evidence gaps and must not be selected by later runners;
- `use_in_primary_score=yes` should be limited to compatible, reviewed validation anchors or active target rows.

Current model-use status:

| Status | Rows |
|---|---:|
| `blocked` | 1 |
| `reporting_only` | 16 |
| `residual_kpi` | 7 |
| `sensitivity_scoring` | 11 |
| `validation_only` | 17 |

## F. Required Anchor Seeds Included or Marked Missing

The companion CSV includes:

- current production and downstream anchors from the C5p_e annual reconciliation;
- current C5p_g residual electricity/NG anchor options;
- C5p_h plant electricity/NG anchor coverage and CO2 boundary rows;
- C5p_i source-card candidate overlay rows and migration recommendations;
- open partial-provenance rows for official full-site electricity, grid-import, NG, and Scope 1 CO2 anchors inherited from prior source-card/candidate-register work; these remain excluded from primary scoring until exact locator, denominator, and boundary review is complete;
- Athanasiadis Table 8/9 model-precedent seed rows supplied by the user in C5p_k; these are partial-locator Rank 3 / Tier B rows, not official Tata truth;
- Badarinath qualitative precedent row, marked methodology/model-precedent rather than official site truth.

Source-rank coverage:

| Source trust rank | Rows |
|---|---:|
| `Rank 1` | 28 |
| `Rank 3` | 8 |
| `Rank 4` | 1 |
| `Rank 5` | 3 |
| `Rank X` | 1 |
| `internal_c5_diagnostic` | 11 |

Evidence-tier coverage:

| Evidence tier | Rows |
|---|---:|
| `Tier A` | 12 |
| `Tier B` | 9 |
| `Tier C` | 3 |
| `Tier E` | 1 |
| `Tier F` | 16 |
| `Tier X` | 1 |
| `internal_diagnostic` | 10 |

Important unresolved source-locator issues:

- Official C0/C1 full-site electricity, grid import, full-site NG, and Scope 1 CO2 anchors now exist as open partial residual-KPI or validation anchors; they still need exact MER/Tata public locators before they can enter primary scoring or thesis claims.
- Athanasiadis Table 8/9 production denominator and natural-gas average basis remain unverified; these rows are user-supplied model-precedent seeds for sensitivity scoring only.
- Badarinath context rows should only be promoted if exact Tata-case/model-precedent statements are located.

## G. Residual KPI Definitions

Later runners should calculate residual KPIs from the register, not from hidden
plug variables.

Definitions:

- `residual_electricity_gross_TWh_y = selected full-site electricity-use anchor - explicit modelled gross electricity demand - selected candidate additions`.
- `residual_grid_import_TWh_y = selected grid-import anchor - modelled net import after generator/steam/internal offsets`, only where the boundary is coherent.
- `residual_NG_PJ_y = selected full-site NG anchor - explicit modelled NG consumers - selected candidate additions`.
- `residual_CO2_Mt_y = selected full-site Scope 1 CO2 anchor - selected CO2 accounting mode`.
- `residual_WAG_TWh_y_or_PJ_y = selected WAG generation/availability anchor - modelled WAG generation/use`, only where carrier boundaries are coherent.
- `residual_per_Mt_active_target = residual / 6.75`.
- `residual_share_of_anchor = residual / selected anchor`.

Negative residuals must be retained and flagged, not floored away. Negative
residuals beyond tolerance indicate possible double counting, wrong
denominator, wrong boundary, or over-expanded candidate sets. Residual KPIs are
reporting diagnostics, not automatic plug variables.

## H. CO2 Anchor Policy

Current CO2 policy:

- `site_anchor_residual_mode`: full-site Scope 1 CO2 anchor is used as validation/reporting residual. No process decomposition is required.
- `aggregate_process_counter_mode`: aggregate process-counter CO2 may be used as diagnostic overlay, but must not be summed with WAG-explicit combustion CO2.
- `WAG_explicit_point_of_oxidation_mode`: BFG/COG/BOFG combustion or carrier-split flare may be reported once at represented sinks using the RVO factor set. This is a partial development-only ledger, not a full-site or ETS total.
- `NG_explicit_represented_consumer_mode`: NG combustion may be reported once for already represented, named consumers using the governed factor. Unallocated site residual NG is not emitted by inference.
- `forbidden_mixed_mode`: aggregate process-counter CO2 plus WAG-explicit combustion CO2 must not be summed into one total.

Current implementation includes a model-wide explicit-fuel coverage ledger:
carrier-specific WAG point-of-oxidation plus named modelled NG consumers. It
remains validation and reporting only; aggregate process counters, capture,
residual energy and Scope 2 remain separate, and ETS-ready is false.

## I. C0 Natural Gas Policy

Current C5 reports C0 modelled NG as zero because explicit modelled NG counts
only NG consumers represented inside the current executable/diagnostic
boundary. C0 full-site NG consumption was not yet represented as a residual /
full-site diagnostic quantity. This does not mean the C0 site uses no natural
gas.

Current C0 NG handling:

- include inherited full-site C0 NG use as an open partial validation/residual KPI anchor while exact public source locator confirmation remains pending;
- do not invent process-level C0 NG consumers unless source-backed;
- report residual C0 NG alongside C1 residual NG as a diagnostic KPI with partial provenance, not as primary scoring or thesis truth;
- classify full-site C0 NG as `residual_kpi` or `validation_only`, not executable process input.

The requested C0 full-site NG example (`12.5 PJ/y`) is recorded as an open
partial-provenance residual-KPI row inherited from prior C5 anchor work. It is
usable for diagnostic residual reporting, but not for primary scoring or thesis
claims until the exact MER/Tata locator and boundary are confirmed.

## J. Anchor Selection and Fallback Logic for Later Runners

Later runners should select anchors by this order:

1. Filter to compatible `model_use_status` values: `validation_only`, `residual_kpi`, or `sensitivity_scoring` as appropriate for the KPI.
2. Prefer the highest source trust rank: Rank 1 before Rank 2, Rank 3, Rank 4, Rank 5.
3. Prefer stronger evidence tier: Tier A before B, C, D/E, F.
4. Prefer exact or partial locator quality over indirect or missing.
5. Require denominator compatibility with the run target.
6. Exclude `conflict_status=blocked` and `model_use_status=blocked`.
7. Fall back from primary validation to secondary validation or reporting context only with an explicit warning.
8. Never fall back to blocked anchors.
9. Warn if multiple same-rank anchors conflict materially.

## K. Preliminary Sensitivity Implications

This document does not design or implement the full sensitivity runner. The
anchor groups most likely to drive later sensitivity scoring are:

- electricity gross use;
- grid import / net import;
- natural gas;
- CO2;
- WAG generation and WAG use;
- production and final product denominator;
- oxygen and utilities where material.

A later task should create
`docs/optimisation/steel/S4/C5_ANCHOR_PARAMETER_SENSITIVITY_DESIGN.md` before
any sensitivity runner is implemented.

## L. GO/NO-GO Recommendations

| Decision | Recommendation |
|---|---|
| Use this anchor register as canonical validation/reporting reference | GO with caveats. |
| Residual electricity KPI reporting | GO as diagnostic/reporting, not dispatch. |
| Residual NG KPI reporting | GO as diagnostic/reporting, not dispatch. |
| C0 full-site NG residual reporting | GO as diagnostic/reporting with partial provenance; primary scoring remains NO-GO. |
| Site-level CO2 anchor reporting | GO as validation/reporting with partial provenance; primary scoring remains NO-GO. |
| Process-level CO2 implementation | NO-GO. |
| WAG-explicit point-of-oxidation CO2 subtotal | GO diagnostic-only for represented BFG/COG/BOFG sinks; no consolidated site claim. |
| Explicit CO2 for named modelled NG consumers | GO diagnostic-only; residual/background NG stays excluded. |
| Consolidated WAG/fuel/site CO2 | NO-GO until non-WAG process carbon, capture and residual boundaries are repaired. |
| Candidate migration to executable development inputs | NO-GO. |
| Economics readiness | NO-GO. |
| DA readiness | NO-GO. |
| Full sensitivity runner implementation | NO-GO; design next only. |

## Risks and Caveats

- This register consolidates current C5 artifacts; it does not prove every underlying source locator.
- Several requested official full-site anchors are explicitly marked open/partial until source-card or PDF locator verification is completed.
- Current C5 diagnostics and source-card candidates are included for traceability, but they are not external validation truth.
- Athanasiadis and Badarinath rows are model-precedent/context rows until targeted locator verification is completed.
- Residual KPI logic must remain visible and diagnostic-only. It must not become a hidden calibration slack or dispatchable load.
