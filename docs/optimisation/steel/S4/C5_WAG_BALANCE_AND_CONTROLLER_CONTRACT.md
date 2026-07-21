# C5 WAG Balance and Controller Contract

## A. Purpose and boundaries

This is the Phase 1 WAG diagnostic for `S4.4c5p_m_wag_balance_and_controller_contract`. It is not a sensitivity run and does not change model equations, executable development inputs, source cards, objectives, residual-load logic, economics, DA, CO2 objectives, or dispatch behaviour.

C5p_k remains exploratory warning evidence only. It used aggregate residual WAG and may bypass existing WAG/controller/mixing surfaces, so it is not accepted as physical WAG allocation evidence.

Anchors are validation/reporting objects, not constraints.

## B. Current WAG balance by configuration and carrier

Carrier-specific rows are preserved from C5p_e where available. Values below are aggregate reporting totals in PJ/y and must not be interpreted as a physical generic WAG carrier.

| Configuration | WAG generated | Process/prep use | Steam/boiler use | Generator use | Flare/spill | Residual after flare | Balance status |
|---|---:|---:|---:|---:|---:|---:|---|
| C0 | 29.140351 | 6.129506 | 1.117922 | 21.892922 | 0 | 0 | pass |
| C1 | 13.885042 | 6.791252 | 0.519397 | 5.736611 | 0.1 | 0.737782 | pass |

The current annual C5p_e carrier rows close arithmetically. The remaining issue is not basic arithmetic closure; it is the absence of a single governed model-wide allocation contract tying process controllers, HSM/sinter/PEFA, steam, generator, flare and common-plant overlays together.

Mixed WAG is not available as a quantitative carrier in this phase. It remains structural eligibility only.

## C. WAG anchor comparison

The `wag_anchor_comparison.csv` file compares only where current anchors are sufficiently interpretable:

- C0 generator electricity: current model is about 2.067665 TWh/y versus 2.0 TWh/y validation anchor.
- C0 product gas reuse 54 PJ/y: partial context only, not exact generator fuel or WAG generation.
- C1 generator preferred fuel and flare anchors: comparable as annual validation, with gap still explicit.
- Athanasiadis WAG generation anchors: model-precedent only; denominator and basis unresolved.

No anchor is used as a constraint or dispatch target.

## D. Existing controller/allocation surfaces

The dependency map records 5 carrier classes and 9 controller/allocation surfaces. Key surfaces are:

- `wag_diagnostic.allocate_process_first`
- `wag_fixed_profile_builder`
- C5l HSM/WBW WAG controllers
- C5m sinter gas/WAG controller
- C5p_b boiler/steam WAG allocator
- C5p_c generator interface allocator
- S4.4b2 structural WAG mixing rules
- C5p_k common-plant overlay as exploratory warning only

These pieces are useful, but they do not yet constitute one authoritative model-wide WAG allocation contract.

## E. Does a model-wide WAG contract exist?

Decision: partial / no single authoritative contract.

Pieces exist: carrier-specific annual balances, HSM/sinter controller surfaces, boiler/steam allocation, generator allocation, and structural mixing eligibility. Missing pieces are the contract that defines precedence and interoperability between them, an explicit common-plant WAG/NG split, and quantitative mixed-gas quality constraints.

Later sensitivities must first create a governed non-executable contract proposal or explicitly call the accepted existing controller outputs. This task does not create that contract as executable logic.

## F. C5p_k status review

C5p_k remains unsuitable as physical WAG allocation evidence. It:

- used aggregate residual WAG;
- did not find an explicit common-plant WAG/NG ratio;
- can bypass or approximate HSM/steam/generator controller surfaces if treated physically;
- may reallocate WAG already accounted for in generator-interface diagnostics.

It can be reused only as warning/context evidence.

## G. WAG error-mode classification

Top warnings in this phase:

- C5p_k aggregate fallback should not be promoted to physics.
- Common-plant carrier split and WAG/NG ratios are missing.
- Mixed WAG has structural eligibility but no quantitative mixer.
- C1 generator flare is aggregate, not carrier-split.
- WAG/fuel-explicit CO2 remains blocked by carbon accounting policy and factor source repair.

`wag_double_counting_warnings.csv` and `wag_contract_gap_register.csv` contain the machine-readable warning and gap rows.

## H. Phase 1 decision gate

| Gate | Decision |
|---|---|
| WAG balance sufficient for non-WAG electricity decomposition | GO_WITH_WAG_CAVEAT |
| WAG-dependent electricity interpretation | NO-GO until controller contract audit |
| NG residual policy | NO-GO until aggregate WAG fallback is removed from physical interpretation |
| CO2 site-level residual reporting | GO_DIAGNOSTIC_ONLY |
| WAG/fuel-explicit CO2 | NO-GO |
| Full sensitivity execution | NO-GO |
| Economics / DA readiness | NO-GO |

## I. Recommended next action

Proceed to electricity boundary decomposition for non-WAG loads in parallel, but keep all WAG-dependent electricity interpretation caveated. Before NG residual policy, WAG/fuel-explicit CO2, or sensitivity execution, create a governed WAG controller contract proposal that reconciles C5l/C5m process controllers, C5p_b steam, C5p_c generators, flare/residual handling, and C5p_k warning context.
