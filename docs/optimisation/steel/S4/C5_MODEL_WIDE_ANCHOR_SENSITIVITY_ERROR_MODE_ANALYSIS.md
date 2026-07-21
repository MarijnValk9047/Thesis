# C5 Model-Wide Anchor Sensitivity Error-Mode Analysis

## A. Purpose and status

This document is a model-wide diagnostic planning artifact for the C5 physical/accounting baseline. It is not a sensitivity run, not an executable-input migration, and not a model-logic change.

The canonical C5 anchor register is the leading validation and reporting source:

- `docs/optimisation/steel/S4/C5_MODEL_ANCHOR_REGISTER_AND_EVIDENCE_HIERARCHY.md`
- `data/03_Optimisation/inputs/assets/steel/S4/c5_model_anchor_register/c5_model_anchor_evidence_register.csv`

This analysis prepares a later phased sensitivity check by identifying likely error modes, parameter/fix levers, expected anchor effects, dependencies on existing WAG/controller functions, and sequencing priorities. Anchors remain validation, reporting, residual-KPI and later scoring objects. They are not dispatch constraints and must not be silently converted into executable development inputs.

C5p_k is treated as an exploratory warning signal only. Its aggregate residual-WAG fallback is not accepted as plant-level WAG allocation evidence because existing WAG generation, mixing, HSM, boiler and generator controller surfaces already exist and must be reconciled before sensitivities build on any WAG allocation logic.

No raw PDFs were inspected for this task. No source cards, model equations, executable inputs, or generated model outputs were changed.

## B. Current anchor status by metric

The companion file `anchor_metric_mapping.csv` records the machine-readable mapping. The current qualitative status is:

| Metric family | Anchor confidence | Boundary clarity | Denominator issue | Later scoring use |
| --- | --- | --- | --- | --- |
| Production / denominator | high for active 6.75 target; medium for raw validation anchors | partial | scaling needed | primary for active-scaled reporting, raw anchors secondary |
| Electricity gross use | medium | partial | some anchors not blindly scalable | secondary scoring or reporting until plant coverage is repaired |
| Grid import / net exposure | medium-low | unclear | not scalable or unknown | reporting only |
| Onsite generation / WAG electricity | high for C0 validation anchor; medium for C1 fuel table | partial | not blindly scalable | validation and sensitivity scoring |
| WAG generation / availability | medium-low | partial | unknown or scaling needed | secondary scoring / reporting |
| Full-site NG | medium | partial | not scalable until source reviewed | residual KPI / reporting |
| Component NG | high for current C1 DRP/EAF/VN25 diagnostics | partial | current activity basis mostly clear | secondary scoring |
| Site-level CO2 | medium | partial | not scalable until source reviewed | residual KPI / reporting |
| Process-level CO2 candidates | low to medium | unclear | activity mismatch possible | sensitivity context only |
| Oxygen / ASU | medium | partial | activity-scaled | secondary scoring / sensitivity |
| Downstream / final product proxy | medium | partial | unresolved denominator | reporting only / secondary |
| Athanasiadis model precedent | medium-low | unclear | denominator and NG basis unresolved | later sensitivity scoring, not primary |

Missing or weak anchors are user/source-card follow-up items. They are not filled with inferred values in this document.

## C. Current model-vs-anchor gap taxonomy

The current C5 stack shows these recurring gap types:

- Missing explicit process load: KGF/coking, BF/BOF/OSF, HSM/WBW, sinter and auxiliary electricity or fuel may be only partial/candidate.
- Residual/background site load: full-site electricity and NG anchors include loads outside the current explicit boundary.
- Wrong denominator/scaling: raw MER/public anchors, active 6.75 Mt/y target, final-product proxy and Athanasiadis model-precedent denominators are not interchangeable.
- Double counting: WAG energy or carbon can be counted in process counters and again at steam/generator/common-plant overlays.
- Undercounted or overcounted WAG generation: BFG/COG/BOFG carrier generation and mandatory self-use need carrier-level checks.
- Too much usable WAG: aggregate residual fallback can overstate what can physically substitute NG.
- Wrong generator/steam/process priority: sink order changes WAG available to generator, steam and common-plant fuel demands.
- Wrong internal-offset boundary: generator and steam offsets must not be treated as DA revenue or hidden grid-import reductions.
- Activity-basis mismatch: LS, crude steel, HRC, final product, coke, DRI and site totals must not be mixed silently.
- Unit conversion mismatch: especially gas volume, NG flow, WAG LHV and non-normalised m3 units.
- Candidate overlay overlap: source-card candidates may duplicate existing `other_modelled_electricity` or process fuel buckets.
- New C1-only asset copied to C0: DRP and EAF must remain excluded from C0 common-plant replication.
- Common C0/C1 asset not represented in C0: full-site C0 NG cannot be interpreted as zero site NG.
- CO2 accounting-mode mismatch: site residual, aggregate process-counter and WAG/fuel-explicit modes must remain separate.

## D. WAG-specific diagnostic risk analysis

WAG is the highest-priority risk area.

### WAG generation too high

This would appear as excessive BFG, COG or BOFG generation or residual WAG versus WAG-electricity and carrier availability anchors. Warning signs include C0 residual WAG feeding generator output above the 2.0 TWh validation anchor and the persistent C1 generator fuel gap. The first test should be carrier-by-carrier generation and use sanity before any plant fuel overlay.

Do not tune WAG generation to force generator anchors.

### WAG availability correct but usable WAG too high

WAG production may be plausible while usable WAG is too high because eligibility, gas quality, Wobbe or mixing constraints are missing. C5p_k is the warning: C0 common-plant fuel demand was fully absorbed by aggregate WAG and no explicit WAG/NG ratio was found.

The next step is a source/function audit. Do not accept aggregate residual WAG as physical allocation evidence.

### WAG sink priority wrong

Existing surfaces include process-first WAG diagnostics, HSM reheat WAG controller, boiler/steam WAG allocator and generator interface allocator. These may not yet form one authoritative model-wide priority contract. Priority affects generator gap, steam fuel demand, flare/residual, NG residual and CO2.

Do not create a new priority rule before reconciling the existing ones.

### WAG double counting

The same WAG can be consumed in process, steam or generator accounting and then reused in candidate overlay or fuel-explicit CO2. Aggregate process CO2 counters and WAG/fuel-explicit combustion must not be summed into a single total.

The immediate rule is mode separation: site-level CO2 residual first, aggregate process-counter mode second, WAG/fuel-explicit later only after carbon policy and factors are repaired.

## E. Existing WAG/controller/function dependency map

The file `existing_function_dependency_map.csv` records the detailed dependency map. Existing controller/allocation surfaces found include:

- `wag_diagnostic.allocate_process_first` and related carrier generation helpers.
- `wag_diagnostic_inputs` governed loaders.
- `wag_fixed_profile_builder` fixed profile and mandatory self-use rows.
- C5l HSM/WBW WAG dispatch and hot-charge/reheat controller surfaces.
- C5p_b boiler/steam WAG allocation.
- C5p_c IJ01/VN25 generator-interface allocation.
- S4.4b2 structural mixing rules and human-review WAG governance pack.

Important gaps remain:

- no single authoritative model-wide WAG allocation contract was found;
- no explicit common-plant WAG/NG split ratio was found by C5p_k;
- no quantitative Wobbe/gas-quality constrained mixer is ready for executable use.

## F. Electricity error-mode analysis

Likely electricity gap causes are:

- missing HSM/WBW electricity;
- missing BOF/OSF electricity;
- missing KGF/coking purchased/gross electricity;
- DSP/downstream coefficient uncertainty;
- ASU/Linde and DRP oxygen-basis sensitivity;
- residual/background site electricity;
- generator/steam offset over-crediting;
- overlap with `other_modelled_electricity`;
- comparing gross site use to net grid import.

C5p_g already reports C0 over-offset explicitly: gross modelled C0 process demand is lower than internal offsets when generator and steam electricity are included. That is a boundary warning, not a basis for hidden flooring.

The next electricity phase should decompose current `other_modelled_electricity` before adding plant candidates one by one.

## G. NG/fuel error-mode analysis

C0 explicit modelled NG is zero because the current boundary counts only represented NG consumers. It does not mean the C0 site uses no NG. Full-site C0 NG belongs in residual KPI reporting unless source-backed process consumers are added later.

C1-only new consumers remain DRP and EAF. They must not be copied to C0. Common plants such as HSM/WBW and KGF/coking can be reviewed only through existing WAG/fuel eligibility rules.

The main risk is that common-plant fuel demand is absorbed by overly flexible WAG. The NG phase is GO only after the WAG allocation audit shows that aggregate residual fallback is not being used as accepted physical allocation.

## H. CO2 error-mode analysis

Current CO2 policy remains:

- site-anchor residual mode: site Scope 1 anchor used for validation/reporting residual;
- aggregate process-counter mode: diagnostic only, not summed with WAG-explicit combustion;
- WAG/fuel-explicit mode later: only after official factors and WAG carbon policy are complete;
- forbidden mixed mode: aggregate process-counter plus WAG/fuel-explicit combustion must not be summed.

Current component diagnostics are not ETS-ready and not full-site totals. DRP captured CO2 must remain a captured/reporting stream, not direct emissions. Scope 2 requires the electricity boundary first.

## I. Production, denominator and downstream error-mode analysis

The executable physical baseline uses the active 6.75 Mt/y target. Raw MER/public 7.2 Mt/y and 6.8 Mt/y anchors remain validation/context anchors unless explicitly active-scaled. Athanasiadis Table 8/9 values remain model-precedent seeds with unresolved denominator and NG basis.

Final-product proxy and liquid-steel-equivalent are not interchangeable. DSP 1.35 Mt/y versus raw 1.5 Mt/y, imported slab and downstream loss/yield assumptions make final-product denominator unsuitable as a frozen economics denominator.

Later sensitivity reporting should retain raw anchors, active-scaled anchors, per-Mt-active-target residuals and final-product proxy diagnostics side by side.

## J. Parameter/fix priority register

The detailed register is `parameter_fix_priority_register.csv`.

P0 priorities:

- WAG carrier balance audit.
- Existing WAG controller/allocation audit.
- WAG sink priority audit.
- Electricity gross/net/import boundary reconciliation.
- Residual electricity and NG KPI definitions.
- CO2 mode separation.

P1 priorities:

- HSM/WBW electricity and reheating fuel candidates.
- KGF/coking electricity and underfiring fuel candidates.
- BOF/OSF electricity and auxiliary gas candidates.
- ASU/Linde and DRP oxygen electricity basis.
- C0/C1 common-plant fuel representation using existing model rules.
- C1 generator gap source review.

P2/P3 priorities include boiler efficiency range, DSP generic coefficient sensitivity, Wobbe/gas-mixing detail and WAG/fuel-explicit CO2 factors after source repair.

## K. Expected effects matrix

The file `expected_effects_matrix.csv` records qualitative expected effects using only:

- `increase`
- `decrease`
- `ambiguous`
- `no_direct_effect`
- `unknown_until_tested`

No sensitivity calculations were executed. The matrix is intended to prevent blind combinatorial sweeps and to make expected directions testable later.

## L. Phased sensitivity-design plan

The plan in `phased_sensitivity_plan.csv` is sequential:

1. Phase 0: freeze inputs and anchor scoring map.
2. Phase 1: WAG balance sanity by carrier.
3. Phase 2: WAG controller/allocation audit.
4. Phase 3: electricity boundary decomposition.
5. Phase 4: NG/fuel residual policy.
6. Phase 5: CO2 site-level residual modes.
7. Phase 6: minimal combined scenarios.

This explicitly avoids a full combinatorial sensitivity sweep until individual levers pass boundary and double-counting checks.

## M. Scoring design for later sensitivity runner

A later runner should report component scores, not a single opaque score. It should include:

- metric-specific raw residuals;
- normalised residuals relative to selected anchor;
- residuals per Mt active target;
- source-rank and evidence-tier weights;
- penalties for negative residuals beyond tolerance;
- penalties for double-counting risk;
- penalties for bypassing existing WAG/controller logic;
- penalties for source-review-required values;
- separate production, electricity, NG, WAG, CO2, oxygen and downstream components.

Blocked anchors must never be selected as fallbacks. Multiple same-rank conflicting anchors should trigger warnings instead of automatic averaging.

## N. GO/NO-GO recommendations

| Item | Decision |
| --- | --- |
| Anchor-informed sensitivity design | GO |
| Full sensitivity execution immediately | NO-GO |
| WAG balance phase | GO |
| WAG controller/allocation audit | GO |
| Electricity decomposition phase | GO after WAG audit or in parallel for non-WAG load decomposition |
| NG residual phase | GO only after WAG allocation is not aggregate fallback |
| CO2 site-level residual phase | GO, diagnostic only |
| Process-level CO2 implementation | NO-GO |
| WAG/fuel-explicit CO2 implementation | NO-GO |
| Migration to executable inputs | NO-GO |
| Economics readiness | NO-GO |
| DA readiness | NO-GO |

The recommended next action is Phase 1 plus Phase 2: perform a WAG carrier-balance sanity check and controller/allocation audit before any sensitivity execution, common-plant NG residual implementation, CO2 fuel-explicit implementation, or economics work.
