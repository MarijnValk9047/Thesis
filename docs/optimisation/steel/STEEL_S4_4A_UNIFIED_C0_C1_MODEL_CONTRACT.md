# Steel S4.4a Unified C0/C1 Model Contract

This `S4.4a` report defines the next-stage unified model architecture and input contract for the public Tata-inspired steel optimisation model. It is a design and readiness artifact only. It does not change any optimisation objective, dispatch logic, candidate input, or thesis-usability status.

Structured companion files are stored under:

`data/03_Optimisation/inputs/assets/steel/S4/s4_4a_unified_c0_c1_model_contract/`

## A. Current-State Audit

`S3.3j` remains the frozen static foundation: a verified, C0-calibrated, C1 boundary-aligned public process-network model. It is not a Tata digital twin and not strict independent C1 validation.

The current `S4.1` to `S4.2e` implementation is a useful C1 DRP/EAF deterministic DA prototype. It includes EAF/DRP physical guardrails, a DRI buffer, DRP/EAF electricity price exposure, DRP NG cost, annualized reconciliation, and a price-insensitive benchmark comparison. It is still DRP/EAF scoped, not full-site Tata economics.

`S4.3b` brings C0 into the common policy framework only as `c0_static_settled`. C0 is settled as a static gross-electricity baseline against the same DAM window. It is not DA-optimised and does not expose C0 physical flexibility.

The next architecture must consolidate these prototypes into one common scaffold rather than stacking more isolated runners.

## B. Unified Architecture Decision

The unified model must represent both configurations through the same input contract:

| Configuration | Role | Current status | Future role |
|---|---|---|---|
| `C0_current_BF_BOF_reference` | current BF-BOF reference | S3.3j static foundation plus S4.3b static-settled baseline | site-scope current-route physical-economic model |
| `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` | hybrid BF-BOF plus NG-DRP plus EAF transition case | S3.3j boundary-aligned plus C1 DRP/EAF S4 prototype | site-scope hybrid physical-economic model |

Differences between C0 and C1 must arise from topology, active assets, buffers, constraints, WAG handling, and source-backed cost structure. They must not arise from manually assigning more or less flexibility by policy.

The current C1 first closures are BF7 inactive and KGF2 / Coking Plant 2 inactive, with BF6 and KGF1 / Coking Plant 1 retained. C1 is a change set over C0, not an unrelated standalone model.

## C. Input Contract

`s4_4a_required_input_tables_manifest.csv` defines the required unified input tables:

- `configuration_assets.csv`
- `process_units.csv`
- `process_io_coefficients.csv`
- `process_energy_intensities.csv`
- `process_emission_factors.csv`
- `buffers_and_stores.csv`
- `wag_generation_coefficients.csv`
- `wag_sink_eligibility.csv`
- `utility_demands.csv`
- `utility_conversion_assets.csv`
- `external_supply_costs.csv`
- `market_price_inputs.csv`
- `production_targets.csv`
- `validation_anchors.csv`
- `policy_modes.csv`
- `solver_and_horizon_config.csv`

Every table must carry source and governance fields where relevant:

`source_card_ids`, `candidate_id`, `evidence_strength`, `input_status`, `thesis_usability`, `codex_may_decide`, `human_review_required`, and `caveat`.

The default rule is `codex_may_decide=false`. Candidate and development-only rows may be used for smoke tests only when explicitly marked as such. Validation anchors must not be silently converted into hourly dispatch inputs.

Long-term source/input architecture:

- source-card register records source metadata;
- candidate-parameter evidence register records sourced values, ranges, units, and locators;
- assumption register records modelling interpretation and educated engineering assumptions;
- physical master workbook records canonical physical topology and component definitions;
- compiled review CSVs are machine-readable workbook snapshots;
- executable development input tables contain only reviewed or explicitly development-only migrated rows;
- stage-gate reports record what is executable, blocked, review-only, or thesis-usable.

Raw PDF / archival source policy: use source cards, candidate evidence registers, the assumption register, and workbook evidence links first. Do not inspect raw PDFs during normal implementation. Raw PDFs under `data/03_Optimisation/inputs/assets/steel/source_evidence/` are archival sources and may be read only in targeted provenance repair, exact locator verification, or conflict-check tasks. Such inspection must produce patch proposals for source cards, candidate evidence, assumptions, or workbook evidence links; it must not create executable inputs directly.

## D. Scope Matrices

The asset, material, energy-carrier, and cost matrices document what is active, tracked, costed, diagnostic-only, deferred, or forbidden. The main boundary decisions are:

- DRP, DRI buffer, and EAF guardrails are reusable C1 prototypes but must be refactored into the unified modelbuilder.
- C0 hourly process flexibility is not yet present.
- Full-site electricity import balance remains blocked until gross load, onsite generation, import/export, and residual-load conventions are source-backed.
- WAG must be represented physically through generation, allocation, sink eligibility, and flaring before any economic interpretation.
- CO2/ETS remains reporting or sensitivity only under the current S4 policy.
- Product revenue, export revenue, grid tariffs, and direct WAG market valuation remain inactive.

## E. Existing Input Mapping

`s4_4a_existing_input_mapping.csv` maps current files into the proposed contract. The main reusable inputs are:

- S3.3j C0/C1 annual anchors as `validation_anchors.csv`;
- S3.4 DRP/EAF development inputs as candidate process, energy, and buffer rows;
- S4.1 DAM price source and window as `market_price_inputs.csv`;
- S4.2c economic policy as `policy_modes.csv` and `external_supply_costs.csv`;
- S4.2d reconciliation outputs as validation/reporting references;
- S4.3b C0 static-settled baseline as context, not as a C0 DA optimisation proof.

No development-only candidate value is promoted to approved thesis input by this mapping.

## F. Missing Inputs and Blockers

`s4_4a_missing_inputs_and_blockers.csv` lists the concrete blockers for a unified model. The blocking categories are:

- C0 hourly physical dispatch variables and constraints;
- C0 material coefficients, yields, buffers, and terminal rules;
- C0 electricity-operation linkage;
- C0 WAG generation, allocation, and boiler/steam utility treatment;
- C1 retained BF-BOF route economics and WAG reduction from BF/coking changes;
- route-neutral downstream/final-product coupling;
- full-site electricity import balance and grid import/export convention;
- residual/background load treatment.

These blockers must be handled before C0 and C1 can be compared as common-scope deterministic DA optimisation models.

## G. Common Policy Modes

Two policy modes are defined for the unified architecture.

| Policy mode | Objective price treatment | Benchmark interpretation |
|---|---|---|
| `price_naive_static_or_cost_smoothed` | no response to hourly DA variation | price-insensitive physical reference settled ex post |
| `deterministic_da_price_taking` | real hourly DAM prices may enter supported electricity-cost terms | deterministic price-taking comparison, not bidding and not oracle |

Both modes must use the same physical constraints, the same hard final-product target, and the same terminal inventory rules. Same policy does not imply same physical flexibility.

## H. Implementation Plan After S4.4a

1. `S4.4b` unified development input tables and schema validators.
2. `S4.4b2` physical master workbook and compiled review CSVs for human review.
3. `S4.4b3` direct/figure-derived provenance and assumption enrichment if source files are available.
4. Human review and migration pack from workbook/candidate/assumption rows into executable development inputs.
5. `S4.4c` unified physical modelbuilder for 24 h C0 and C1 with static-price regression, solving only executable migrated rows.
6. `S4.4d` unified economic layer for all modelled site-scope flows, with source reconciliation.
7. `S4.4e` price-naive versus deterministic DA comparison for C0 and C1.
8. `S4.4f` 168 h deterministic extension and readiness gate for S5 bidding and later stochastic layers.

Oracle/perfect foresight is postponed until unified deterministic C0/C1 DA is stable. Bidding, clearing, stochasticity, CVaR, quarter-hour, D+4, and mFRR remain blocked until then.

## I. Stage Gate

S4.4a status: `pass_to_s4_4b_with_limitations`.

S4.4b may proceed because the architecture and input contract are now explicit. The unified model is not ready for thesis claims or oracle work. The current outputs are development-contract evidence only.

Implementation note after S4.4b: the unified development input tables and validator now live under `data/03_Optimisation/inputs/assets/steel/S4/s4_4b_unified_dev_inputs/` and `scripts/Data/04_Steel_Test_Case/run_s4_4b_unified_input_validation.py`. The input layer is structurally valid but remains development-only with blockers preserved. S4.4c is the first modelbuilder phase after the S4.4b2/S4.4b3 review and migration controls.

Implementation note after S4.4b2: the physical master workbook lives under `data/03_Optimisation/inputs/assets/steel/S4/s4_4b2_physical_master_workbook/`. Its decision is `ready_for_human_physical_model_review`, not executable model readiness. Workbook and compiled-review rows require human review and explicit migration before use in S4.4c or later.

Implementation note after S4.4b3: `data/03_Optimisation/inputs/assets/steel/S4/s4_4b3_direct_pdf_provenance_review/` remains blocked with `migration_allowed=false` until reviewed source-card, candidate-evidence, assumption, or workbook-evidence patches are migrated. The raw Athanasiadis and Badarinath PDFs are archived under `source_evidence`, but direct PDF presence does not make any row executable or thesis-usable.

Implementation note after S4.4c: the first unified physical regression runner is `scripts/Data/04_Steel_Test_Case/run_s4_4c_unified_physical_regression.py`. It confirms that the S4.4b input layer can solve the C1 DRP/EAF physical slice under a price-naive static regression, while C0 remains blocked for missing executable hourly physical inputs. S4.4d economics may proceed only with this limitation explicitly preserved.

Implementation note after S4.4c3: `scripts/Data/04_Steel_Test_Case/run_s4_4c3_static_physical_closeout.py` audits the later asymmetric 24 h and 168 h C0/C1 static physical runs. Both configurations solve as development evidence, but C0 depends on a deterministic fixed binary slot schedule classified as `heuristic_not_benchmark_ready`. The closeout decision is `pass_static_physical_closeout_but_daily_guardrail_required`; hot/cold slab and WAG/utility equation work may proceed with that caveat, while economics and benchmark weekly operation remain gated.
