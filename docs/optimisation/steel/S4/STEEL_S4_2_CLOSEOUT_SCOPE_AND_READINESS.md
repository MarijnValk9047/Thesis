# Steel S4.2 Close-Out Scope And Readiness

## Purpose

This report closes out the current `S4.2` steel optimisation stage after `S4.2e`.

It explains what the current model does, what it does not do, how it relates to source-backed `C0` and `C1` annual anchors, and what should come next. It is an audit/reporting artifact only. It does not change the optimisation objective, dispatch logic, candidate inputs, or thesis-usability status.

Structured companion files:

- `data/03_Optimisation/inputs/assets/steel/S4/s4_2_closeout_scope_and_readiness/s4_2_closeout_scope_inventory.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/s4_2_closeout_scope_and_readiness/s4_2_closeout_policy_inventory.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/s4_2_closeout_scope_and_readiness/s4_2_closeout_source_reconciliation.csv`
- `data/03_Optimisation/inputs/assets/steel/S4/s4_2_closeout_scope_and_readiness/s4_2_closeout_stage_gate.json`
- `data/03_Optimisation/inputs/assets/steel/S4/s4_2_closeout_scope_and_readiness/s4_2_closeout_stage_gate.csv`

## Gate Decision

| Item | Decision |
|---|---|
| S4.2 close-out status | `pass_with_limitations` |
| Active solved S4 configuration | `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` DRP/EAF guardrail wrapper |
| C0 status | economic policy prepared, not executed |
| Thesis usability | development evidence only |
| Objective or dispatch changed by this report | no |
| Recommended next stage | `S4.4` unified C0/C1 model-contract and deterministic scaffold before oracle/perfect foresight |

The current `S4.2` result is strong enough to proceed to a bounded next design gate, but not strong enough to support full-site Tata economic claims.

Implementation note after close-out: `S4.3a` now creates a C0/C1 common-policy comparison artifact. `S4.3b` adds C0 static-settlement support because true C0 DA optimisation is not yet physically supported. C0 is settled as a static gross-electricity baseline against the same DAM window, while the companion blocker report lists the missing C0 hourly decision variables and constraints needed for real DA optimisation.

Implementation note after S4.3: `S4.4a` now records a unified C0/C1 model contract and input-schema plan. The next stage should consolidate the physical-economic scaffold rather than proceed directly to oracle/perfect foresight.

## A. Configurations

| Configuration | Status | Solved In S4 | Source Alignment | Can Claim | Cannot Claim |
|---|---:|---:|---:|---|---|
| `C0_current_BF_BOF_reference` | prepared/static baseline only | no | partial | S3.3j remains the frozen C0-calibrated public baseline | no C0 S4 hourly price response or C0 economic benchmark |
| `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` | partly implemented | yes, scoped wrapper | partial | DRP/EAF guardrail price-taking under fixed final-product proxy | no full C1 utility, WAG, grid, or downstream economics |
| S4.1/S4.2 active DRP/EAF price-taking layer | implemented development-only | yes | partial | deterministic 24 h DA price-taking under physical guardrails | no bidding, clearing, stochasticity, QH, CVaR, mFRR, product revenue, export revenue |
| C0 S4 economic policy | prepared_not_executed | no | partial | common policy fields exist for future comparability | no C0 solved result |

## B. Plants And Assets

The active S4.2 optimisation layer is narrower than the full S3.3j process-network baseline.

| Asset | Current S4.2 Status | Costed In Objective | Steered | Caveat |
|---|---|---:|---:|---|
| Coking plant | deferred | no | no | S3/S3.3j context only |
| Sinter plant | deferred | no | no | S3/S3.3j context only |
| Pelletizing/imported pellets | partly modelled as DRP pellet input | no | yes | no pellet procurement or pelletizing economics |
| Blast furnace | deferred in S4 | no | no | C0/S3.3j context only |
| Hot metal buffer | deferred | no | no | no S4 hot-metal inventory |
| BOF | deferred in S4 | no | no | no BOF hourly batch scheduling |
| DRP | implemented development-only | DRP NG and electricity | yes | continuous bounded DRP with ramp; values are candidate/dev only |
| DRI buffer | implemented development-only | no | yes | finite buffer and terminal equality active |
| EAF | implemented development-only | electricity via S4.2c | yes | hourly semi-continuous binary abstraction, not heat sequencing |
| Secondary metallurgy/caster | deferred/diagnostic context | no | no | no active S4 steering |
| Downstream/final product pass-through | proxy only | denominator only | constrained target | final product is a pass-through proxy |
| HSM/downstream | deferred | no | no | no HSM/downstream scheduling in S4.2 |
| Boilers/steam utility | deferred | no | no | 6 PJ/y sink remains governance placeholder |
| WAG allocation/flaring | deferred | no | no | no direct WAG valuation |
| Vattenfall/interface | deferred | no | no | no dispatch/profit or hourly offset |
| Grid import/export | blocked/disabled | no | no | no net-grid import cost or export revenue |

## C. Materials

| Material | Balanced | Buffered | Terminal Rule | Costed | Final-Product Relevance | Evidence Status |
|---|---:|---:|---:|---:|---|---|
| Coal/coke | no in S4.2 | no | no | deferred | upstream C0 context | S3/S3.3j context |
| Iron ore/sinter/pellets | pellets only | no | no | deferred | DRP input | candidate/dev |
| Hot metal | no in S4.2 | no | no | no | C0 context | S3.3j context |
| Scrap | diagnostic expression | no | no | no | EAF diagnostic | candidate/dev |
| DRI/HDRI | yes | yes | yes | no | main EAF feed | candidate/dev |
| Liquid steel | internal technical diagnostic | no | no | no | not primary KPI | candidate/dev |
| Slabs/WIP/final product | proxy only | no | no | no revenue | thesis-facing cost denominator | downstream/pass-through proxy |
| WAG streams | no in S4.2 dispatch | no | no | forbidden direct valuation | energy boundary context | validation/context only |

## D. Energy Carriers And Utilities

| Carrier | Modelled In Physics | Costed In Objective | Reported Only | Validation Target Only | Deferred Or Forbidden |
|---|---:|---:|---:|---:|---|
| Electricity | DRP/EAF only | DA cost for DRP/EAF electricity | yes | full-site anchors only | fixed/background and grid balance deferred |
| Natural gas | DRP only | fixed-price DRP NG | yes | full-site gas anchor only | boiler/utility gas split deferred |
| BFG | no | forbidden direct valuation | context | yes | deferred |
| COG | no | forbidden direct valuation | context | yes | deferred |
| BOFG | no | forbidden direct valuation | context | yes | deferred |
| WAG aggregate | no | forbidden direct valuation | context | yes | deferred |
| Steam/boiler fuel | no explicit variable | no internal steam price | yes | 6 PJ/y placeholder | deferred |
| Oxygen | diagnostic expressions | no | yes | no | oxygen balance/cost deferred |
| Vattenfall/internal generation | no | no | yes | yes | hourly offset deferred |
| Grid import | no | no | yes | yes | net-grid import economics blocked |
| Grid export | disabled | no export revenue | yes | no | export revenue forbidden |
| CO2/ETS | no active steering | objective forbidden | deferred/reporting only | future reporting target | no CO2-optimised dispatch |

## E. Active Policies

| Policy | Current Status |
|---|---|
| Deterministic hourly DA price-taking | implemented for C1 DRP/EAF wrapper |
| Price-insensitive benchmark | implemented as zero-price early-feasible guardrail tie-breaker |
| Hard final-product target | implemented as final-product pass-through proxy |
| No product revenue | active policy |
| No export revenue | active policy |
| No grid tariffs | active policy |
| No direct WAG market valuation | active policy |
| Fixed NG price convention | implemented for modelled DRP NG at 0.35 EUR/Nm3 |
| CO2/ETS reporting/sensitivity only | active policy; not objective steering |
| C0/C1 common economic policy | prepared; C0 not solved |
| S4.2d source reconciliation gate | passed as reporting-only gate |
| S4.2e benchmark comparison | passed under S4.2c cost basis |

## F. Source Reconciliation

Current source reconciliation uses the existing `S4.2d` and `S4.2e` outputs.

| Comparison | Status | Result |
|---|---|---|
| DRP/EAF electricity annualized vs C1 total electricity anchor | expected_scope_gap | 5.187672 PJ/y vs 16 PJ/y |
| DRP NG annualized vs C1 total gas anchor | expected_scope_gap | 21.027088 PJ/y vs 47 PJ/y |
| C1 grid offtake anchor | not_comparable | 10 PJ/y anchor, but no S4 grid balance |
| Internal/Vattenfall generation | deferred | 6 PJ/y anchor, no hourly generation offset |
| WAG reuse | deferred | 54 PJ/y anchor, mixed electricity/steam and no direct valuation |
| S3.3j 6 PJ/y utility sink | not_comparable | governance placeholder, no S4.2 boiler variable |
| S3.3j 3 PJ/y NG + 3 PJ/y WAG split | not_comparable | internal allocation placeholder, not measured data |
| Badarinath-aligned NG price | pass | 0.35 EUR/Nm3 used as development-only convention |
| S4.2e total modelled external-cost saving | pass | 24,385.135 EUR, 3.0965689%, 4.129434 EUR/t final product |

Interpretation: the source-backed annual anchors do not invalidate the current S4.2 result, but they confirm that it is a scoped DRP/EAF development result rather than a full-site annual Tata economic model.

## G. Claims And Non-Claims

### S4.2 Can Claim

- DRP/EAF-scoped deterministic DA price-taking reduces modelled external cost under fixed production and physical guardrails in the 24 h development smoke case.
- `S4.2e` saving is valid for the current modelled DRP/EAF scope and S4.2c economic policy.
- The current result separates electricity-only savings from electricity-plus-DRP-NG modelled external-cost savings.
- Annualized `S4.2d` values are useful scale checks against C0/C1 public anchors.

### S4.2 Cannot Claim

- full-site Tata cost optimisation;
- C0 versus C1 full economic comparison;
- independent validation of Tata hourly operations;
- WAG/Vattenfall dispatch economics;
- grid import/export economics;
- CO2-optimised dispatch;
- product revenue, profit, or margin optimisation;
- bidding, clearing, stochastic, CVaR, mFRR, or quarter-hour performance.

## H. Next Implementation Plan

1. `S4.4b` unified development input tables and schema validators.
2. `S4.4c` unified 24 h physical modelbuilder for C0 and C1 with static-price regression.
3. `S4.4d` unified economic layer for source-supported site-scope flows with reconciliation.
4. `S4.4e` price-naive versus deterministic DA comparison for C0 and C1.
5. `S4.4f` 168 h deterministic extension and readiness gate for S5 bidding and later stochastic layers.

Open methodological decision: if C0 economics must be thesis-facing before oracle work, the unified C0/C1 deterministic scaffold should remain the priority over any isolated oracle benchmark.

## I. Readiness Summary

`S4.2` is closed as `pass_with_limitations`.

Prerequisites for the next unified deterministic stage:

- implement S4.4b input-table validators before modelbuilder work;
- reuse the same source and governance rules for C0 and C1;
- preserve hard final-product target and DRI terminal rule;
- do not add market layers or unsupported objective terms.

Prerequisites for C0/C1 economic comparison:

- implement or define a C0-compatible runner;
- avoid assigning C0 the C1 DRP/EAF flexibility;
- keep source-backed annual anchors as validation targets rather than hidden hourly profiles;
- decide whether C0 economics should precede oracle work.

The current result remains development evidence only.
