# C5 Model State and Deterministic Optimisation Roadmap

## Decision in one sentence

Current gate: `blocked_before_final_weeks_pending_non_final_rolling_week`.
Phase 5K freezes the user-authorized represented boundary after 56/56 validation
and 56/56 newly frozen held-out models pass. The promoted contract uses the
shared 90% electricity baseload, a constant 7 PJ/y site NG service in both
configurations, a reporting-only common 2.0 MtCO2/y direct-emissions residual,
zero residual steam and a C0-only 0.95 WAG-yield multiplier. The WAG adjustment
is an explicit development fallback, not a source-identified carrier
correction. It reduces held-out C0 WAG to 54.485 PJ/y and flare to 0.080 PJ/y.

Phase 6A has been rerun on that exact fingerprinted boundary. All 168 evaluated
models and all physical, information-timing, bid and settlement checks pass.
Phase 6B adds an hourly Strict LEAR D--D+4 ten-scenario bid--clear--redispatch
chain on one day and one seven-day engineering fixture. The accepted a03 run
passes 256/256 gates with all 156 bidding, redispatch and terminal-target
selection solves optimal. Phase 6C extends the same engine to 15-minute
intervals and passes the matched 27-April--3-May week with 203/203 checks and
112/112 optimal model builds. Phase 6D then validates the shared internal-QH
EAF implementation physically; its Gate A passes with zero validation failures,
while one 120-hour C1 S10 solve remains a disclosed performance time-limit.
The four-regime D-only/S10 input and executor contracts pass, including one
complete C0 winter A/B/C diagnostic. The original C1 24-hour physical horizon
is infeasible, but the governed 24-hour economic plus 48-hour physical split
horizon passes. V1 `expected_cost_incumbent` remains the promoted representative
planning mode. The corrected conditional minimum-imbalance gate first proved a
positive 4.787437-MWh physical minimum in the former typical/calm C1 blocker.
A validation-derived feasibility-only clearing-pattern block subsequently
repairs that exact 2-March case to 0 MWh without a minimum-imbalance solve or a
physical-bound change. The former 906.454-second `S0_C1_responsive` runtime
blocker is now repaired by exact bid-signature symmetry breaking plus
`MIPFocus=1`; the same frozen problem proves optimality in 255.535 seconds
including production progress. The definitive augmented method fixes the
economic-scenario binary incumbent only during its reduced feasibility-aware
canonicalisation. It remains three-process reproducible and keeps the S10
objective and probabilities unchanged. A restricted parent-round bridge fixes
only the economic-scenario binaries during an auxiliary warm-start solve and
then restores the complete MILP; it closes the exact two-path expected-cost
blocker in 372.184 seconds. The earlier four-shadow-mask source blocker is now
superseded by the governed non-final validation-pattern contract and fixed
0.2% economic-gap policy. The resumed S0--C1 constraint-generation gate, all
nine synthetic cases and all thirteen non-final shadow/regime cases pass with
numerical zero imbalance. The next unfinished gate is one frozen non-final
maintenance-free rolling week with C0/C1 and A/B/C. Final weeks and every
sensitivity remain blocked. Causal D--D+4 support also remains blocked.
CVaR and mFRR have not completed. The freeze is
for a physically and terminally
validated represented procurement boundary, not a full-site digital twin,
exact annual anchor replication or ETS-ready emissions account.

The fixed-reference deterministic procurement-cost path, pre-DAM
operational-hardening validation, bounded VN25 development response and
governed D-D+4 point-forecast integration and deterministic response diagnostics
previously passed. The pre-benchmark decision was
`price_response_valid_anchor_coverage_partial`, not `DAM_ready`. C0 and C1 use
machine-readable cumulative route bands with
actual 23/24/25-hour local-day execution deadlines inside timestamp-derived
119/120/121-hour replans; no hourly production profile, historical C0
calendar or free route substitution is imposed. The cost baseline
`steel_s2_fixed_reference_deterministic_cost_v3_20260716` is retained, while
`steel_s2_pre_dam_operational_boundary_closure_v1_20260720` supersedes its
rolling execution-bias interpretation and passes 9/9 closure checks.

The represented external-procurement objective covers net grid electricity,
named NG, purchased dry coking coal, PCI, represented sinter/PEFA ore,
imported DR pellets, represented purchased scrap and actual imported slab.
For the general deterministic rolling price-response path it solves lexicographically:
minimum cumulative production-progress deviation first, represented procurement
cost second, then the governed physical tie-breaker within the preserved
optima. This supersedes the cost-first ordering after that ordering accumulated
343-528 t of C1 production credit and broke recursive rolling feasibility.
The representative stochastic-study exception preserves the first two optima
but selects their V1 incumbent without a planning physical tie-break; actual
redispatch continues to use the full physical tie-break hierarchy.
The promoted aggregate electricity baseload is priced only through net grid
purchase. Annual NG, steam and direct-CO2 gaps, BFG/COG/BOFG, internal
generation, inventory, revenue and ETS remain unpriced. BF pellets
are an explicit unrepresented scope gap; HBI is inactive.

The corrected central execution annualises to 6.75 Mt/y for both C0 and C1;
the numerical residual is below 0.0002 t/y and maximum carried production
credit is 0.000003 t. Represented executed procurement cost is EUR 34.232
million for C0 (EUR 264.437/t final product) and EUR 61.047 million for C1
(EUR 471.577/t). Cost identity, material/origin conservation, carrier-specific
WAG, steam, utilities and residual exclusion all pass.

The rolling controller now carries cumulative completed production into every
later replan. Local deadlines and the next execution-block progress target are
adjusted by production credit/debt, so flat-price replanning no longer resets
and repeatedly exploits the +0.5% first-block edge. The governed +/-0.5%
envelope, capacities, continuous-operation rules and endogenous hourly
throughput remain intact. The former 6.78375-Mt/y executed view is retained as
a superseded diagnostic, not current central output.

Post-cost reconciliation is
`steel_s2_post_cost_reconciliation_v2_20260716`; no independent matching
variable-procurement cost benchmark exists. The bounded sensitivity family
`steel_s2_fixed_reference_cost_sensitivity_v1_20260716` passes 35/35 response
and physical checks across 16 solved lineages. The flat price-series run
reproduces the central run exactly, while
`steel_s2_price_series_interface_validation_v1_20260716` validates 1,176
synthetic forecast-index rows without realised-future leakage, DAM bidding or
settlement. The four-case VN25 validation uses a 0-to-350-MW upper-bound
development abstraction. Missing minimum-load/start/ramp/outage/CHP features
are omitted, not invented; IJ01 stays non-price-responsive. The governed
LEAR/Lago D-D+4 `y_pred` contract is now integrated for deterministic
price-response analysis. The corrected one authorized Phase 5B export
sensitivity completed but failed its material threshold and gross-import
guardrail, so export revenue remains inactive and the accepted no-export
central model is frozen. Only the governed Phase-6B/6C fixtures and the
fail-closed representative-regime executor define the only permitted
price--quantity bidding, realised clearing and risk-neutral S10 interfaces.
Representative D-only/S10 execution and the S30 sensitivity are blocked until
the new behavioural recourse gate passes under the 24e48p contract and promoted
V1 planning selection. Causal
D--D+4 execution, annual claims, CVaR, mFRR and live-market operation remain
inactive, and active BF routes still lack a BF-pellet burden.

## 1. Role and document precedence

This is the mandatory human-readable task-start document for C5 work. It
records the current implementation surface, established learnings, boundary
limits and next gate. It replaces older append-only model-state narratives.

Use sources in this order when they conflict:

1. `AGENTS.md` for repository-wide working rules.
2. `docs/optimisation/PROJECT_DECISIONS.md` for frozen methodological policy.
3. This document for the active C5 implementation state and next task.
4. Current executable code, resolved configs and comparable run manifests.
5. Canonical source cards, component ontology and anchor register.
6. Older C5 reports as historical or diagnostic evidence only.

File recency and words such as `canonical`, `baseline` or `gate` do not make a
report authoritative. A new task must confirm the baseline fingerprint below
before changing code or launching a broad audit.

## 2. Active baseline fingerprint

| Purpose | Active surface | Comparable evidence | Status |
|---|---|---|---|
| C0/C1 quota feasibility | `run_s4_4c5p_ae_rolling_production_feasibility.py` with `configs/steel_quota_driven_physical_feasibility.yaml` | `data/03_Optimisation/runs/c5_gate1_sinter_basis_smoke_v3_20260715/` | pass: C0 and C1 solve, all cumulative quotas pass, terminal material balances close and carrier-specific WAG residuals are zero; C0 overproduction is an operation-class guardrail result, not anchor closure |
| Thesis-scale quota test | same runner and config with the recorded 18,493.150685-t/day quota override | `data/03_Optimisation/runs/c5_gate1_sinter_basis_thesis_v3_20260715/` | C0 solves exactly at 129,452.054795 t; C1 is infeasible because retained BF6 plus DRP capacity permits at most 125,052.200001 t, a 4,399.854794-t shortfall |
| Closed-loop mechanism | `run_s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py` with the two Gate-2 configs | `steel_gate2_closed_loop_endogenous_6_75_v4_20260716` and `steel_gate2_closed_loop_mer_site_product_v5_20260716` | C0 passes three 24-hour executions and inventory handoffs in both runs; zero-import C1 remains the labelled expected-infeasible stresscase; MER-site C1 passes all rolling, material, origin and carrier-WAG guardrails, so Gate 2 is complete |
| Gate-3/4 corrected rolling reconciliation | same p_af runner with `configs/steel_gate3_annual_physical_anchor_reconciliation.yaml` and `configs/steel_gate4_mer_reference_validation.yaml` | `steel_gate4_endogenous_week_anchor_contract_v1_20260716` and `steel_gate4_mer_reference_validation_week_v3_20260716` | seven-block endogenous and MER-reference modes pass quota, handoff, material, origin, carrier-WAG, electricity-identity and Mode-B checks; corrected reference scoring is 0 of 4 primary configuration/family pairs, with 3 contextual pairs; economics remain locked |
| Gate-4 bounded sensitivities | p_af scenario overlays on the reference config | `steel_gate4_sensitivity_wag_volume_envelope_v1_20260716` and `steel_gate4_sensitivity_hsm_electricity_0104_v1_20260716` | both pass all physical guardrails; generator volume-envelope and 0.104-MWh/t-HRC cases remain source-bounded sensitivities and are not promoted to the central parameterisation |
| Post-Gate-4 source/boundary repair | same p_af runner with `configs/steel_source_boundary_evidence_repair.yaml` in paired endogenous/reference mode | `steel_source_boundary_repair_downstream_v3_20260716`, `steel_source_boundary_repair_generator_v1_20260716` and `steel_source_boundary_repair_electricity_v1_20260716` | all three accepted families pass seven replans for C0/C1 with Gurobi; their historical 2/4 score is invalid because it counted route-derived production aggregates as independent validation |
| Final pre-economics methodology/boundary closure | same p_af runner and config; governed route and future-cost contracts in the existing component ontology | `steel_final_pre_economics_boundary_acceptance_v2_20260716` | four physical configuration/mode cases pass with Gurobi; 72/72 validation checks pass across paired modes; independent pre-cost primary annual-anchor score is 0 and no longer a readiness gate; decision is `ready_for_deterministic_energy_cost_design`; objective remains inactive |
| Ex-post deterministic procurement-cost accounting | reusable p_bc module called through the existing p_af reporting entrypoint; governed price/policy and extended cost-flow contracts in the component ontology | `steel_s2_ex_post_cost_accounting_v1_20260716` derived from accepted v2 `endogenous` | 18/18 accounting checks pass without a solver; only net grid import, named NG and actual slab delivery are priced; physical fingerprints are unchanged; route-cost coverage remains incomplete and objective activation is NO-GO |
| Fixed-reference scenario and procurement boundary | `c5_fixed_reference_scenario_contract.csv`, extended route/cost contracts and p_af | `steel_s2_fixed_reference_procurement_physical_v2_20260716` | price-free C0/C1 baseline passes seven replans with cumulative 24-hour execution deadlines; represented external PCI/PEFA-ore flows are active and BF pellets/HBI remain explicit gaps |
| Complete ex-post procurement cost | reusable p_bc on the fixed-reference procurement physical parent | `steel_s2_complete_ex_post_procurement_cost_v1_20260716` | 20/20 checks pass; eight price families and 24 flow mappings reconcile by component, route and configuration; objective remains inactive |
| Fixed-reference deterministic procurement cost | unified builder and p_af lexicographic mode | `steel_s2_fixed_reference_deterministic_cost_v3_20260716` | all 28 Gurobi solves optimal; C0 6,097/49/7,336 and C1 8,281/49/8,238 variables/binaries/constraints; cost optimum is preserved within EUR 0.01 and all physical guardrails pass |
| Post-cost reconciliation | same solved v3 lineage, no second dispatch | `steel_s2_post_cost_reconciliation_v2_20260716` | cost identity residual below EUR 0.000001; two primary-comparable rows exist and neither is below 7.5%; no matching independent variable-procurement cost benchmark exists |
| Bounded price/generator responsiveness | 15 child runs plus reused v3 central under the same fixed route bands | `steel_s2_fixed_reference_cost_sensitivity_v1_20260716` | 35/35 checks pass; own-basket costs and 168-hour objectives are monotonic, high electricity/NG prices do not increase their external use, and the source-bounded 0.34 VN25 efficiency case increases grid import |
| Pre-DAM price-series interface | governed series contract and rolling slice adapter | `steel_s2_flat_price_series_interface_validation_v1_20260716`; `steel_s2_price_series_interface_validation_v1_20260716` | flat series reproduces v3 exactly; six interface checks and 1,176 synthetic forecast rows pass without future-information leakage, bidding or settlement; decision `ready_for_future_DAM_price_integration` |
| Final S2 acceptance/explanation audit | extended p_bh completion audit; no re-dispatch | `steel_s2_final_acceptance_explanation_audit_v1_20260717` | production-envelope cause, complete C0/C1 waterfalls, economic coverage and both generator-anchor gaps close methodologically; all checks pass; final decision `ready_for_governed_DAM_data_contract` |
| Pre-DAM operational-boundary hardening | cumulative rolling progress tier plus same-run carrier WAG, generator and procurement audits | `steel_s2_pre_dam_operational_boundary_closure_v1_20260720` | one corrected central and two focused Gurobi families pass; 9/9 closure checks pass; C0/C1 execution tracks 6.75 Mt/y and carrier balances close; exact VN25/IJ01 and BF-pellet evidence gaps change the current decision to `DAM_data_contract_only_operational_gaps_remain` |
| Bounded VN25 development price response | generator operating-mode contract, existing price-series adapter, unified builder and p_af rolling runner | `steel_s2_vn25_development_price_response_v1_20260720` | four Gurobi cases are optimal with zero failed guardrails; flat development mode reproduces the reference physics, 100 EUR/MWh_e keeps VN25 NG at zero, 220 activates NG up to the 350-MW cap, and IJ01 remains non-price-responsive; decision `development_VN25_price_response_ready` |
| Governed hourly D-D+4 point forecast | existing price-series adapter, unified p_af rolling builder and `run_s4_4c5p_bk_hourly_da_dplus4_forecast_integration.py` | `steel_s2_hourly_da_dplus4_point_forecast_integration_v1_20260720` | five 120-hour-plan/24-hour-execution cases pass; all 70 C0/C1 Gurobi models are optimal, the mandatory price-insensitive benchmark is included, flat adapter parity is exact, validation and frozen held-out windows each contain seven replans, final C0/C1 production is exactly 6.75 Mt/y, and decision is `ready_for_deterministic_DAM_price_response` |
| Deterministic response and configuration-matched anchor diagnostics | timestamp-aware p_af runner and `run_s4_4c5p_bl_deterministic_price_response_anchor_diagnostics.py` | `steel_s2_deterministic_price_response_anchor_diagnostics_v1_20260720` | pass: 444/444 Gurobi models optimal; flat adapter parity, identical-state y_pred dominance, separately labelled perfect-foresight regret, unit/cost identities, VN25 break-even response and all rolling physical guardrails pass; longest coherent held-out support is 4,321 h (49.326%) and is explicitly `partial_year_not_annual`; decision `price_response_valid_anchor_coverage_partial` |
| Phase 5B bounded C0 export sensitivity | corrected eight-state exact comparator reconstruction plus the existing p_af rolling runner | `steel_c5_phase5b_c0_export_sensitivity_v2_20260727` | stop: 4/4 trajectories and 56/56 models optimal, 14/14 containment replans pass and terminal-band excess is zero; neither development week reaches the 0.015014-TWh_e/y WAG-electricity threshold and both increase gross grid import; decision `phase5b_threshold_or_guardrail_failed_retain_and_freeze_no_export_central` |
| Phase 5B resource-capped breakthrough oracle | corrected eight-state comparator plus blockwise no-higher-gross-import and no-higher-named-NG caps; physical endpoint removes only economic-optimum preservation | `steel_c5_phase5b_breakthrough_tests_v1_20260727` | stop at February gate: no-export and physical-upper-bound trajectories pass, 28/28 models are optimal, 7/7 containment and resource-cap audits pass, but certified WAG-electricity gain is -0.000000077 MWh numerical noise versus the required +287.939726 MWh; clean economic export and July correctly not run |
| Phase 5C source-mechanism adjudication | official Athanasiadis/Badarinath definitions plus the frozen February/July no-export DEVELOPMENT trajectories; zero solves | `steel_c5_phase5c_source_mechanism_adjudication_v1_20260727` | the old DRI level-correlation and absolute BF-throughput checks are retired; corrected DRI-change correlation is positive in both weeks, BF asset efficiency stays non-comparable, no physics/economics change is justified, and frozen terminal-aware held-out validation becomes the next gate |
| Phase 5D source-backed NG mechanism closure | opt-in non-endogenous split inside the existing 3.07-PJ-LHV/y flexible other-site heat service; no export and unchanged physical demands | `steel_c5_phase5d_source_backed_ng_mechanism_closure_v1_20260727` | historical DEVELOPMENT sensitivity: 28/28 models pass, but 8.005 of 9.655 PJ/y remains an anonymous fixed component and therefore violates the later carrier-specific residual criterion; Phase 5E supersedes its promotion and retains it sensitivity-only |
| Phase 5E source-backed annual anchor closure | exact 2025 MER annual energy/Scope 1 partitions plus unchanged no-export rolling physics | `steel_c5_phase5e_source_backed_anchor_closure_v1_20260727` | pass: 14/14 primary annual families, 6/6 carrier-coverage gates, 2/2 generator balances, 28/28 rolling models and 24/24 dynamic checks pass; C0/C1 named NG coverage is 100%, electricity 83.2%/91.0%, CO2 100%; WAG-electricity attribution is 2.519/1.197 TWh/y; Phase 5D is nonpromoted and Phase 6 execution waits for frozen held-out validation |
| Phase 5F HSM COG/NG controller | QRA design-flow mixture shares plus explicit user-authorized 24-hour development blocks in the unchanged no-export rolling model | existing HSM-enabled p_af lineage and `test_s4_4c5p_phase5f_hsm_qra_mixture.py` | pass: default C0/C1 volume shares are 55/45 and 20/80 COG/NG; BFG/BOFG stay excluded; C0 anonymous NG is displaced hourly; February/July pass 28/28 models; released WAG increases generator use or flare without changing production; the 24-hour block is not a source-proven operating timescale |
| HERACLES blocker-resolution evidence gate | page-verifiable review of the definitive 124-page technical Part B; zero solves and no executable-input change | `C5_HERACLESS_BLOCKER_EVIDENCE_GATE.md`; `STEEL-SC-0016`; `WD02` | evidence gate complete: 85/15 is operating time rather than output allocation; DRI/EAF availability and state logic support later bounded tests; DRI energy supports validation; steam and holder remain topology-only; HSM timescale, VN25 minimum rate, full WAG allocation, BF6/BF7 denominator and held-out validation remain unresolved |
| Phase 5G baseload integration and final-freeze attempt | source-service overlap contract, constant electricity/NG interfaces, retained HSM and four frozen validation periods | `C5_PHASE5G_FINAL_DETERMINISTIC_FREEZE_GATE.md`; `steel_c5_phase5g_final_deterministic_freeze_v1_20260728` | fail closed: 112/112 models, 194/194 physical checks and 8/8 HERACLES checks pass, but the selected 90% electricity load activates enough C0 generator NG to worsen the C0 NG anchor error from 64.0% to 90.3%; attempted baseloads are nonpromoted, held-out is not admitted, model freeze and Phase 6 remain blocked |
| Phase 5H four-residual diagnostic | zero-default electricity/NG/steam/direct-CO2 contract, Athanasiadis Figure 38 evidence and fresh period freeze | `C5_PHASE5H_FOUR_RESIDUAL_EFFECT_AND_FREEZE_GATE.md`; `steel_c5_phase5h_four_residual_final_selection_gate_v1_20260728` | fail closed as a four-residual contract because no defensible normal-operation steam maximum exists; 560/560 permitted diagnostic models pass and only 10% electricity remains source-compatible; conditional 90% NG/CO2 rows are not promoted |
| Phase 5I electricity-only represented-boundary freeze | promoted 10% electricity contract and four fresh held-out periods | `C5_PHASE5I_ELECTRICITY_ONLY_FREEZE_GATE.md`; `steel_c5_phase5i_electricity_only_heldout_freeze_v1_20260728` | pass: 56/56 rolling models and all physical/component gates pass; exact C0/C1 loads are 15.707829645/17.538616398 MWh/h, other residuals remain zero, and decision is `represented_boundary_deterministic_model_frozen_for_phase6` |
| Phase 6A deterministic DA purchase bidding and settlement | frozen Phase-5I point-forecast schedule, flat-price reference, isolated y_true oracle and realised-price settlement | `C6_PHASE6A_DETERMINISTIC_DA_BIDDING_SETTLEMENT_GATE.md`; `steel_c6_phase6a_deterministic_da_bidding_settlement_v1_20260728` | pass: 168/168 evaluated models, 408/408 physical checks and 13/13 timing/accounting checks pass; executable bids use forecast-origin information only, oracle is never submitted, and Phase-6B scenario-contract design is next |
| Phase 6B hourly stochastic DA bid--clear--redispatch | frozen Phase-5K physics, Strict LEAR D--D+4 point/S10 inputs, common steel bid grid, realised-D clearing and exact physical redispatch | `C6_PHASE6B_HOURLY_STOCHASTIC_DA_BID_CLEAR_REDISPATCH_GATE.md`; `steel_phase6b_hourly_da_bid_clear_redispatch_a03_20260730` | engineering validation pass: 16 day/week policy trajectories, two price-insensitive terminal-target selections, 256/256 checks and 156/156 optimal solves; a02--a03 cost/production parity is exact |
| Phase 6C QH stochastic DA bid--clear--redispatch | shared granularity-aware Phase-6B engine, frozen QH D--D+4 point/S10 inputs, hourly terminal bands and matched seven-day support | `C6_PHASE6C_QH_DA_BID_CLEAR_REDISPATCH_GATE.md`; `steel_phase6c_qh_da_bid_clear_redispatch_a01_20260730` | bounded engineering validation pass: eight C0/C1 policy trajectories, 56 replans, 112/112 optimal model builds and 203/203 checks; hourly `dt=1` parity passes; the QH/hourly delta combines price and physical granularity and is not annual economic evidence |
| Pre-matrix behavioural and economic-rationality gate | frozen synthetic profiles plus four non-final shadow days; V1 Strict S10 QH bid--clear--redispatch | `20260801_pre_matrix_behavioural_gate_v1` | BLOCK after S0 C0 passes 37 physical checks and S0 C1 planning solves optimally but actual-price intervalwise clearing has no feasible complete redispatch path; remaining synthetic, all shadow and all final-week runs are not started |
| Transparent source-emulation prescreen | existing annual ledgers, frozen target/parameter contracts and the analytical-only prescreen | `steel_c5_tata_benchmark_v1_20260721` | reviewed complete: five PeFa overlays rejected before rolling; KGF and PeFa remain frozen with `may_move=false`; no eligible rolling candidate exists; decision `source_valid_emulation_rejected` |
| Source-driven representative-period validation | frozen four validation/four held-out periods, three governed strategies and cached deterministic C0/C1 cases | `steel_c5_source_emulation_validation_v1_20260721` | pass: 24/24 cases and physical guardrails pass; MER C1 DRI is scenario-definition consistency context and zero strict independent quantitative MER families remain; whole-period procurement-cost differences are descriptive arithmetic pending a terminal-inventory value bridge; reviewer decision `complete` |
| User-authorized full-site emulation Checkpoint 4 | five retained development candidates, two development weeks and cached deterministic C0/C1 solves | `steel_c5_user_authorized_full_site_emulation_v1_20260722` | stop-rule complete: 30/30 cases and 420/420 solver models are optimal with all physical gates passing; cache-only independent review `complete`; the reviewed baseline/`recovery_bg25` pair advanced to the separate held-out checkpoint while all overlays retained sensitivity-only status |
| Real-anchor energy-recovery Checkpoint 6 | independently selected eight-week TEST set, source-driven baseline plus `recovery_bg25`, and three governed strategies | `steel_c5_real_anchor_energy_recovery_v1_20260722/checkpoint6` | independent review `complete`: 48/48 cases and 672/672 models optimal; 24 raw fixed-background flags preserved and disposed as serialization false positives (0.00412 MWh/y, 5.2e-9 relative), with zero material physical failures; source baseline central, `recovery_bg25` sensitivity-only/nonpromoted; aggregates are `weighted_annual_equivalent_from_representative_held_out_weeks`, not an annual backtest |
| C0 real-anchor mechanism experiment | source baseline plus four frozen nonpromoted repair candidates over two DEVELOPMENT validation weeks and three governed price cases | `steel_c5_real_anchor_mechanism_experiment_v1_20260723` | 15/15 fingerprint-checked caches reused, 210/210 models optimal and all guardrails pass; lower NG activates generator NG only in volatile cases; zero flexible NG is allocation-location non-identifiability under the builder tie-break, realised WAG spreads remain diagnostic, source baseline stays central, and decision is `lower_ng_activates_generator_ng_in_volatile_cases_allocation_location_tiebreak_selected_stop_no_second_search` |
| Gate-2 boundary-reconciliation evidence | source cards, MER Table 5.2, EU FMP BREF, JICA engineering yield and the same p_af runner | `steel_gate2_closed_loop_mer_site_product_v5_20260716`; older sprint runs retained as diagnostics | 1.10 HSM is retired as an unlocated broad proxy; 1.06 is the rounded MER-boundary development central independently supported by lower generic technical ratios; central site scrap is 1.9 Mt/y and is not duplicated as two route allocations; the 1.07/1.03 solved case remains `development_feasibility_sensitivity` only |
| C1 annual physical context | `run_s4_4c5p_bb_canonical_c1_physical_baseline.py` | `steel_c1_canonical_physical_baseline_v2` | exact 6.75-Mt/y MER-site-product case, pass with boundary caveats |
| Annual anchor closure audit | `run_s4_4c5p_aw_annual_multi_anchor_reconciliation.py` with `configs/steel_gate1_anchor_closure_audit.yaml` | `c5_gate1_anchor_closure_reconciliation_v4_20260715` | one independent comparable family is below the strict 7.5% threshold; production target excluded; anchor-stop readiness is false (1 of 4) |
| Operating classes | `steel/s4_4c_component_ontology.py` and `c5_component_ontology/c5_builder_operation_class_overrides.csv` | source-carded operation-class rows plus focused tests | C0 KGF1/KGF2, sinter and BF6/BF7 use `fix_on_over_horizon`; throughput remains unfixed and bounded, while BOF and downstream classes are unchanged |

Required task-start values:

- C0 availability policy: `quota_driven_binary_capacity`;
- C1 availability policy: `quota_driven_topology`;
- planning horizon: 168 hours for the retained physical/cost baseline and 120
  hours only for the explicit D-D+4 forecast contract;
- execution/quota block: 24 hours;
- cumulative quota semantics: lower-bound progress inside the governed
  envelope, with an exact cumulative terminal equality in the D-D+4
  seven-execution validation;
- active C0 coke interface: 1.285 t dry coal/t coke and 0.359 t coke/t hot
  metal, both source-card-backed development coefficients;
- sinter activity/output interface: `t_iron_ore/h` activity converted by 1.230
  t sinter/t iron ore before the sinter inventory and per-t-sinter consumers;
- active BF represented-sinter proxy: 2.1041666667 t hot metal/t represented
  sinter; not a complete burden recipe;
- active Gate-2 HSM conversion: 1.06 t slab/t HRC, a rounded MER-boundary
  development central supported by lower independent technical yield evidence;
- active Gate-2 scrap contract: 1.9 Mt/y central site supply, 1.0 Mt/y BOF
  consumer guardrail, 1.8 Mt/y EAF operational guardrail and 0.272727273 t
  EAF scrap/t liquid steel; the 2.8-Mt/y site value is substitution sensitivity;
- price-free physical-baseline market prices and cost objective: disabled;
  governed central electricity, NG, material and slab prices are active only
  in the fixed-reference cost mode and its derived ledgers;
- historic 5/4/9-hour C0 schedule: rejected as an active baseline.

If a task cannot confirm these values, it must report a repository consistency
issue. It must not substitute a static C0 report.

## 3. Configurations and production basis

| Item | C0 current reference | C1 Phase-1 hybrid |
|---|---|---|
| Route | BF6/BF7, KGF1/KGF2, sinter, BOF and downstream | retained BF6/KGF1/BOF plus NG-DRP/EAF and downstream |
| Inactive assets | none by topology | BF7 and KGF2 |
| Active development target | 6.75 Mt/y final-product proxy | 6.75 Mt/y final-product proxy |
| Daily thesis-scale quota | 18,493.150685 t/day | 18,493.150685 t/day |
| Public context | about 7.2 Mt/y liquid steel | about 6.8 Mt/y liquid steel; MER site-product context includes imported slab |

Final product, endogenous liquid steel, imported slab, HSM output and DSP
output remain separate measures. The project must not silently equate final
product with liquid steel or scale an anchor with an incompatible denominator.

## 4. Established learnings — do not restart by default

### Production and material boundary

- The historic C0 5/4/9-hour calendar is an inherited regression profile. Its
  coke deficit is a valid negative diagnostic for that profile only; it is not
  evidence that the C0 route requires those hours.
- The earlier root-level `steel_quota_driven_physical_feasibility_v2` proves
  both configurations could solve the smoke quota before C0 continuous-class
  enforcement. It is retained as pre-Gate evidence and is not the accepted
  enforced-continuous result.
- The Gate-1 validation fixes only the KGF1/KGF2, sinter and BF6/BF7 on
  variables. It adds 840 on-state rules over 168 hours and does not fix their
  throughput, BOF commitment, downstream throughput, route shares or hours.
- Rolling production deadlines are cumulative lower bounds, not exact final
  output equalities. Continuous availability may therefore cause
  overproduction, which is reported rather than suppressed with a fixed
  profile.
- The accepted C0 coke-chain interface uses 1.285 t dry coal/t coke and 0.359 t
  coke/t hot metal from the coking and blast-furnace source cards. These remain
  governed development coefficients, not Tata operating truth.
- At the smoke quota of 41,336.4 t, C0 solves optimally at 109,252.896611 t.
  All seven cumulative deadlines pass, coke/sinter/hot-iron/cold-slab terminal
  residuals are zero, and the maximum carrier-specific WAG balance residual is
  zero. C1 also solves optimally at the quota.
- The old thesis-scale C0 sinter-capacity diagnosis was invalid because it
  added a `t_iron_ore/h` activity directly to a `t_sinter` inventory. With the
  source-card conversion of 1.230 t sinter/t iron ore applied in both model and
  diagnosis, C0 solves optimally at the 129,452.054795-t thesis quota. All
  seven cumulative deadlines pass, terminal material residuals are zero and
  the maximum carrier-specific WAG residual is zero.
- C1 remains infeasible at the thesis quota. The active terminal-balanced
  envelope is 60,095.000001 t on the retained BF6 route plus 64,957.2 t on the
  DRP-EAF route, or 125,052.200001 t total (17,864.6 t/day). The binding
  source-backed/development bounds are BF6 at 170 t represented sinter/h and
  DRP at 550 t pellets/h with the governed conversion chain. The shortfall is
  4,399.854794 t over 168 hours.
- The sinter activity is explicitly iron-ore feed. Inventory, COG and any
  activated electricity term use converted sinter output. The BF proxy implies
  0.4752475 t represented sinter/t hot metal and remains a partial represented-
  burden development value; pellets and direct ore are deferred, coke is
  separately balanced and PCI is not a closed burden-flow term.
- KGF2 and BF7 bounds remain explicitly labelled development proxies rather
  than Tata-measured operating limits. The diagnosis does not authorise a
  residual coke supply, a fixed schedule, a route share or silent coefficient
  replacement.
- The exact all-endogenous C1 6.75-Mt/y stress case has no accepted solution.
- `steel_c1_canonical_physical_baseline_v2` remains static context only. Rolling
  feasibility is proven separately by
  `steel_gate2_closed_loop_mer_site_product_v5_20260716`; the zero-import C1
  case remains the labelled infeasible stresscase.
- Imported slab is an explicit external material boundary, never a residual,
  free store or upstream-output substitute.

### WAG, steam, electricity and NG

- BFG, COG and BOFG remain separate physical carriers where source rows
  preserve them. `mixed_wag` is structural-only and `aggregate_wag` is
  reporting-only. C5p_k is warning/context only.
- Eligible WAG precedes named, explicitly permitted NG backup. No fixed
  plant-level WAG/NG ratio and no Wobbe model may be introduced.
- The historical repaired reference ledger reports 5.864607 PJ/y C1 generator
  WAG plus flare. The accepted central cost run reports 6.696078 PJ/y versus
  the independent 10.6-PJ/y MER component anchor (-36.829%). VN25 named NG
  remains zero versus 4.1 PJ/y because neither the physical nor cost contract
  contains a source-backed rolling minimum generator load, hours or NG blend.
  The model does not force either anchor through an annual fuel target, fixed
  WAG/NG ratio or full-site NG residual.
- VN25 now has separate BFG, COG, BOFG and named-NG inputs and a 0.345
  development electricity conversion. IJ01 has separate eligible WAG inputs,
  no NG and a 0.8-PJ/y backup envelope; its quantitative electricity/steam
  split remains deferred and is conserved as a named unallocated output
  bucket. Both unit fuel identities close.
- The 15-bar steam/boiler bridge and generator internal-electricity offsets
  are usable diagnostics, not a full-site steam network or market interface.
- Gross electricity, internal generation and represented net import remain
  separate. Named NG uses a common-LHV reporting basis; background electricity
  and full-site NG remain visible residuals, never model inputs.
- The final repaired reference gross loads are 2.210982 TWh/y for C0 and
  3.454409 TWh/y for C1. The 45-MW Linde N2 auxiliary load is separate from
  ASU/O2, EAF secondary metallurgy and boiler/steam auxiliary electricity stay
  explicit known-but-non-executable zero buckets, and the old exact C0 3-TWh
  site proxy is retired from the physical boundary and anchor scoring.

### Emissions and anchors

- Mode-B explicit-fuel CO2 is counted at represented oxidation sinks. The
  current model-wide diagnostic subtotals are 6.374735 Mt/y for C0 and
  4.692801 Mt/y for C1.
- These figures exclude unrepresented non-fuel carbon and must not be combined
  with aggregate BF/BOF/KGF/PEFA/sinter counters or claimed as full Scope 1 or
  ETS totals.
- The canonical anchor register contains 52 source-ranked seeds. Official
  Tata/MER evidence is primary; Athanasiadis is model-precedent; Badarinath is
  secondary context.
- Anchors are comparison objects, never dispatch constraints. The <7.5%
  proximity threshold applies only to individually boundary-comparable rows.
- The post-cost comparison has two independent primary-comparable rows: VN25
  named NG and generator WAG plus flare. Neither is below 7.5%. The exact
  production target and all route-derived volumes remain scenario definitions.
  The absence of a matching independent variable-procurement benchmark and the
  two visible generator gaps are evidence limitations, not quantities to fit.

## 5. Current connected-layer status

| Layer | Current status | Remaining limitation |
|---|---|---|
| Topology and material balances | C0 and C1 pass the smoke quota; corrected thesis-scale C0 passes; C1 origin-tagged annual case remains available | all-endogenous thesis-scale C1 is 4,399.854794 t above the active combined route capacity |
| C0 continuous assets | KGF1/KGF2, sinter and BF6/BF7 are fixed on over the horizon; throughput remains bounded and quota-driven; Gate 1 is complete | no fixed hours or throughput are authorised; development coefficients retain their stated evidence limits |
| C1 continuous assets | ontology rows support `fix_on_over_horizon`, but the accepted fixed-reference config has `use_c1_component_ontology_continuous_classes=false`; C1 on-state and throughput remain endogenous inside topology, route bands and capacity bounds | do not describe this accepted lineage as C1 fixed-on or as fixed throughput; reopening the optional override requires a separate physical-policy test |
| BOF/EAF and downstream | batch-equivalent/bounded ontology and metallics/origin ledgers exist; C0 has free endogenous HSM/DSP routing and scaled cumulative reference bands with explicit BOF/HSM/DSP losses | raw C0 7.2/5.4/1.5 annual rows remain context/scenario definitions, not simultaneous active targets |
| Carrier WAG | carrier-specific generation and governed sink contracts exist | no quantitative mixer; C1 flare is not fully carrier-split |
| HSM/PEFA | HSM uses the default user-authorized 24-hour QRA COG/NG development controller; PEFA remains a partial throughput-linked controller | HERACLES confirms more WBW2 NG as COG declines but not the QRA shares or real 24-hour timescale; activate only source-traceable routes and keep BFG/BOFG excluded from HSM |
| Steam/boilers | represented 15-bar bridge | not complete site steam closure |
| Generators | VN25/IJ01 carrier-specific WAG and named-NG interface, unit fuel identity and internal electricity offset | annual fuel use is post-cost validation; IJ01 quantitative CHP split is explicitly deferred outside the first cost layer; no export, DA revenue or economic-dispatch claim |
| Electricity/NG | named represented buckets close without overlap; DRP/EAF use primary MER activity bases; C0 exact site proxy is retired; named consumers remain separated from residuals | full-site electricity/NG residuals and boiler/steam auxiliary electricity remain reported and excluded from the first objective |
| CO2 | Mode-B represented-fuel diagnostic | not full Scope 1/ETS |
| Rolling execution | active p_af executes 168-hour plans in seven 24-hour handoff steps for the representative-week comparison | C0 and central C1 MER-site pass; the import-free C1 case remains the labelled Gate-2 stresscase; the complete week, first transient, stable blocks and planned horizon are reported separately |
| Annual physical reconciliation | p_af annualises only the same solved executed blocks for reporting | physical ledger passes; initial-inventory/lower-bound-quota transients are retained and are not a simulated annual production claim; independent pre-cost annual-anchor score is 0 and is not a readiness gate |

## 6. Immediate implementation sequence

### Gate 1 — C0 continuous-operation enforcement

1. Reuse the source-classified C0 KGF1/KGF2, sinter, BF6 and BF7 rows.
2. Wire source-backed continuous availability through the existing unified
   builder interface.
3. Keep throughput quota-driven within source-backed capacity and material
   constraints. Do not impose fixed hours, a calendar or fixed throughput.
4. Preserve BOF as batch-equivalent and downstream as bounded.
5. Run smoke and thesis-scale quota configurations and report what binds.

Exit criterion: an active configuration-matched C0 result or a focused
infeasibility diagnosis from the quota-driven model.

Current status: complete. Focused tests pass; the normal C0/C1 smoke run passes
the quota, material, carrier-WAG, residual and market-disabled guardrails; and
the corrected C0 thesis-scale solve passes the same checks. C1 thesis scale
remains infeasible, reproduced by the active BF6 and DRP capacity envelope
without residual supply or unsupported coefficients. Annual anchor closure is
separate and remains 1 of 4 independent comparable families below 7.5%.

### Gate 2 — active closed-loop quota run

After Gate 1, connect or revalidate the existing p_af inventory-handoff
mechanism with the active quota-driven policy. Report every 24-hour executed
block and inventory handoff; do not annualise it as simulated truth.

Current status: complete. In both active Gate-2 runs C0 solves three replans,
produces 19,200 t in each executed block against the 18,493.150685-t quota,
carries all represented inventories forward, preserves continuous
KGF1/KGF2/sinter/BF6/BF7 availability, and closes represented material and
carrier-specific WAG balances.

The `endogenous_6_75` C1 case remains the intended zero-import stresscase. Its
C1 solve is expected-infeasible and no imported slab is available; this is a
diagnostic case result, not a Gate-2 failure. The `mer_site_product` case is the
accepted rolling boundary case and solves all three C1 replans optimally.

The 2026-07-15/16 evidence resolution found that 1.10 t slab/t HRC was an
unlocated broad development proxy. Its input/output basis is slab into HSM per
tonne HRC out, applied equally to endogenous BOF, endogenous EAF and imported
slab. The MER annual material boundary implies 1.05364-1.06455 across the
existing DSP conversion range and no more than 1.07273 even with zero DSP
loss. EU FMP-BREF loss references and a JICA engineering-design yield
independently support lower ratios. Gate 2 therefore uses the rounded 1.06
development central while retaining DSP at 1.05. The 1.10 value is historical
high-loss sensitivity only.

The scrap audit also corrected semantics rather than increasing capacity. MER
Table 5.2 gives a central 1.9-Mt/y site supply, 1.0-Mt/y BOF consumption and
0.9-Mt/y EAF consumption at 3.3 Mt/y EAF liquid steel. The active EAF recipe is
therefore 0.9/3.3 = 0.272727273 t scrap/t liquid steel. The EAF 1.8-Mt/y and
site 2.8-Mt/y values are operational high-scrap DRI-substitution variants, not
extra steelmaking capacity. Active constraints use the central 1.9-Mt/y site
supply cap plus distinct BOF 1.0- and EAF 1.8-Mt/y consumer guardrails. Their
sum exceeds the site cap, so no route split is fixed and the same central
allowance is not applied twice. Intermediate 24-hour caps prevent rolling
budget reuse; the static horizon cap alone enforces the final deadline.

In `steel_gate2_closed_loop_mer_site_product_v5_20260716`, each 168-hour C1
plan produces exactly 129,452.054795 t and minimises imported slab to
7,160.621929 t per plan, about 373,375 t/y horizon-equivalent and below the
600,000-t/y cap. The three executed blocks use 273.972604, 1,643.835624 and
1,643.835624 t imported slab. Their 72-hour annualised import rate is
433,333.335327 t/y; annualisation remains reporting-only. Origin residual is
zero in the annual ledger, imported-slab upstream site burdens are zero,
material residuals are at reporting tolerance, BFG/COG/BOFG balances close,
and no residual input or fixed route split is active.

The earlier 1.07-HSM/1.03-DSP solved run remains
`development_feasibility_sensitivity`. It proves the architecture but is not
the central parameterisation. The accepted v5 annual ledgers come from the
same solved rolling lineage and are available for Gate 3; they are not by
themselves anchor closure. Gate 3 reconciled that lineage physically in v4;
its historical 2-of-4 anchor interpretation is superseded by the corrected
Gate-4 contract below. Costs, DA, stochasticity, mFRR and ETS remain locked.

### Gate 3 — configuration-matched annual reconciliation

Only after C0 and C1 physical guardrails pass:

1. reconcile final-product and origin denominators;
2. compile carrier-specific WAG source-to-sink ledgers;
3. report gross electricity, internal generation, net import and residual;
4. report named NG separately from full-site residual NG;
5. report Mode-B fuel CO2 separately from Scope-1 residual;
6. compare only boundary-compatible anchors.

Current status: the v4 physical ledger remains a passing historical Gate-3
lineage, but its 2-of-4 anchor interpretation is superseded. It labelled HSM
slab input as output, let C1 rows mask C0 family gaps and did not consistently
honour scenario-definition and primary-score flags. Gate 4 now reports HSM
slab input, material loss and HRC output separately; maps only named NG to
component anchors; separates thermal WAG, generator WAG, WAG electricity and
flare; and scores by configuration plus independent family. The 6.75 target
and all reference production bands are excluded from validation.

### Gate 4 — bounded sensitivities and pre-economics stop

Historical status: complete with a pre-economics stop that was later
superseded by the boundary repair, fixed-reference cost implementation and
final S2 audit below. The endogenous and MER
reference runs each solve seven replans for C0 and C1. In the reference run the
complete executed C1 week annualises to 7.036262 Mt/y, the first block to
7.977220, stable blocks to 6.879436 and the first planned horizon to exactly
6.75; all are deterministic annual equivalents, not a simulated year. Import
is respectively 0.574321, 0.470250, 0.591667 and 0.581464 Mt/y and remains
below the 0.6-Mt/y cap. Origin and carrier residuals are zero.

C1 uses narrow cumulative BOF, EAF, HSM, DSP and import bands scaled to the
6.75-Mt/y site-final-product proxy. These are scenario definitions. C0 retains
the executable Gate-1 topology: its public HSM/DSP rows remain non-comparable
because an independently evidenced executable C0 DSP/output-conversion route
compatible with the governed coke chain is absent.

Two sensitivities were run. The generator `volume_envelope_only` case changes
the planned-horizon internal WAG electricity by +0.112761 TWh/y and net grid
import by -0.112761 TWh/y at unchanged gross demand. The HSM 0.104-MWh/t-HRC
case changes planned gross and net-grid electricity by +0.180076 TWh/y. Both
pass all physical guardrails and remain sensitivities, not central values. No
NG/steam/Mode-B coefficient was changed because no additional closed,
primary-comparable component boundary supports it.

At that historical gate, corrected reference coverage was zero of four required primary
configuration/family pairs below 7.5%, with three contextual pairs. The anchor
register currently provides no independent primary energy/NG/CO2 family that
these sensitivities could close. Gate 4 therefore stops `NO-GO` for
deterministic cost-design planning. Source/boundary evidence repair is the next
permitted work; do not fit anchors with residuals or unsupported assumptions.
This is retained as lineage evidence and is not the current next-gate decision.

### Post-Gate-4 targeted source/boundary repair

Current status: complete and superseded by the final pre-economics acceptance
below. The three accepted paired repair runs use the same
168-hour/24-hour/seven-replan p_af lineage and require
`gurobi`/`gurobi_direct`. All quota, handoff, material, origin, carrier-WAG,
generator-energy, electricity, steam and Mode-B checks pass.

The C0 interface derives a C0-specific HSM input/output factor of 1.0416667
from the raw 7.2-Mt/y liquid-steel, 5.4-Mt/y HSM-output, 1.5-Mt/y DSP-output and
1.05 DSP conversion rows. It combines this with the source-card BOF recipe of
0.875 t hot metal and 0.208 t scrap per tonne liquid steel. Raw annual rows are
used once to derive/scaled-reference the route and are excluded from validation
when imposed; endogenous routing remains free within hourly and horizon caps.
Using the source-card DSP conversion range 1.03-1.07 gives a corresponding C0
HSM input/output sensitivity range of 1.036111-1.047222; it is documented but
was not activated as a tuning run.

The unit-specific generator and electricity repairs improve comparability but
do not make the MER energy anchors true by construction. In the final reference
run generator WAG plus flare is 5.864607 PJ/y versus 10.6 and VN25 NG is zero
versus 4.1. Represented gross electricity is 7.959535 PJ/y for C0 versus the
13.7-PJ/y full-site context and 12.435871 PJ/y for C1 versus 17.8. These signed
gaps remain reporting/validation evidence and are never supplied as residual
loads or fuels.

The formerly reported 2-of-4 score is invalid. C0/C1 liquid-steel totals and
other aggregates derived from the governed reference route are scenario
definitions even when surfaced through the paired repair comparison. They are
excluded from independent validation, restoring the score to zero.

### Final pre-economics methodology and boundary closure

Current status: complete. The accepted v2 paired run executes C0/C1 endogenous
and reference modes with Gurobi. Across 28 solves, all statuses are `ok` and
all termination conditions are `optimal`; 72 validation checks pass with zero
failures. Material reporting residuals are at most 0.000015 t per execution
block, origin residuals are zero, carrier-WAG residuals are zero and annual
electricity/generator/steam accounting residue remains below 0.001 MWh/y.

The final source review makes four C1 energy activity bases explicit without
changing production capacity or route policy:

- DRP named NG: 9.9 GJ-LHV/t DRI from MER reduction plus furnace rows;
- DRP electricity: 0.083333 MWh/t DRI from the MER 0.3-GJ/t row;
- EAF arc plus secondary electricity: 0.422222 + 0.031 MWh/t liquid steel;
- EAF named NG: 0.05 GJ-LHV/t liquid steel.

The 195-Nm3/t-pellets DRP modelling precedent and its annual dispatch gap are
no longer used as the central cost-bearing basis. HSM, DSP and Linde N2 remain
explicit accepted development values; ASU, EAF and DRP central intensities use
their primary source-card locators. Generator annual fuel quantities are
post-cost operational anchors, while the pre-cost generator requirement is its
carrier eligibility, capacity/envelope and conversion identity.

The authoritative machine-readable route and cost-boundary contracts are
`c5_component_ontology/c5_route_boundary_contract.csv` and
`c5_component_ontology/c5_future_cost_boundary_contract.csv`. Every future
priced flow has a carrier, unit, activity driver and source status. Residual
electricity/NG and WAG are excluded from price terms.

### Ex-post deterministic procurement-cost accounting

Historical intermediate status: complete and superseded by the complete
material ledger and accepted fixed-reference objective. The governed specification is
`economics/DEVELOPMENT_ECONOMIC_FINANCIAL_LAYER_COSTS.md`; executable scenario
and policy inputs are `c5_external_supply_costs.csv` and
`c5_cost_policy_modes.csv`. The reusable p_bc module is called through the
existing p_af reporting entrypoint and reads only the accepted endogenous
`executed_hourly.csv`.

C0 reports zero represented external procurement cost because its solved
represented grid import and named NG are both zero; its 42,329.250997 MWh
internal-generation offset is reported but not priced. C1 reports EUR
20,025,663.662075 over the executed 168 hours, or EUR 142.166768436/t executed
final product. This comprises EUR 5,458,291.476160 grid electricity, EUR
10,403,399.040265 named NG and EUR 4,163,973.145650 for 7,856.553105 t actual
imported slab. The annualised value is reporting only.

At that point the next gate was raw-material procurement-boundary closure. The
represented coking-coal, PCI, sinter/PEFA ore, DR-pellet and purchased-scrap
boundaries now close in the fixed-reference path. BF pellets remain an explicit
non-free scope gap and HBI remains inactive, so endogenous route-economic and
total-production-cost claims are still prohibited.

### Fixed-reference S2 final acceptance

Current status: complete. The accepted central lineage remains
`steel_s2_fixed_reference_deterministic_cost_v3_20260716`; the derived audit is
`steel_s2_final_acceptance_explanation_audit_v1_20260717`. It reuses the
accepted physical, ex-post, cost, reconciliation, sensitivity and price-
interface artifacts without another Gurobi run.

Every complete 168-hour plan is exactly 6.75 Mt/y equivalent. Repeated first
blocks annualise to 6.78375 Mt/y because the flat-price timing optimum is
degenerate and the inventory-minimising physical tie-break selects the
permitted +0.5% first-deadline edge. Cost waterfalls close at EUR 34.154162
million for C0 and EUR 61.068469 million for C1 over 168 executed hours. The
EUR/t values are not directly comparable total-cost results because the fixed
configurations and represented external-input boundaries differ.

VN25 NG remains 0 versus 4.1 PJ/y: NG-generated electricity costs about EUR
159.42/MWh_e at the central 55-EUR/MWh-LHV price and 0.345 efficiency, versus
EUR 80/MWh_e grid power, while no governed minimum VN25 service is active.
Generator WAG plus flare remains 6.696078 versus 10.6 PJ/y because the current
carrier-conserving process/self-use allocation leaves that residual for VN25
and no flare. Both are classified operating-policy/scenario evidence gaps, not
implementation defects or fitting targets.

That audit's historical decision was `ready_for_governed_DAM_data_contract`.
It is superseded by the operational-hardening result below.

### Pre-DAM operational boundary closure

Current status: pass with classified operating-data gaps. The run
`steel_s2_pre_dam_operational_boundary_closure_v1_20260720` performs one
corrected central and two focused diagnostic Gurobi families. All three solve
optimally through seven C0/C1 replans and all 9/9 closure checks pass.

The cumulative production-progress state removes the systematic first-block
bias: the corrected central annual equivalents are 6,749,999.999973 t/y for C0
and 6,749,999.999869 t/y for C1. Hourly throughput remains endogenous and the
+/-0.5% route envelope remains available. Same-run BFG/COG/BOFG ledgers close;
the maximum CSV reconstruction residual is 0.000257 MWh and all model carrier
residual checks are zero. C1 generator WAG plus flare is 6.727462 PJ/y versus
10.6 PJ/y, and VN25 NG is 0 versus 4.1 PJ/y. Neither anchor is forced.

Central and high-electricity cases keep VN25 named NG at zero. Higher
electricity price slightly increases useful VN25 WAG and lowers grid import.
The 0.34-efficiency case preserves a 0.34 electricity/fuel conversion versus
0.345 central; its endogenously different route/WAG quantity is not treated as
a fixed-fuel comparison. IJ01 remains zero because no source-backed minimum or
quantitative CHP conversion is active.

External represented flows are priced once. Purchased scrap remains the
explicit development boundary because no internal recycle-origin loop exists;
HBI is inactive. C0/C1 represented costs remain not directly comparable total
costs because BF-grade pellet quantity/burden and a matching independent cost
benchmark are absent.

That lineage's decision was `DAM_data_contract_only_operational_gaps_remain`.
It is superseded for the bounded development generator abstraction by the
validation below; its evidence-gap classifications remain valid.

### Bounded VN25 development price response

Current status: pass. The run
`steel_s2_vn25_development_price_response_v1_20260720` executes four complete
168-hour-plan/24-hour-execution rolling cases. Every C0/C1 replan terminates
optimally with Gurobi. C1 models 8,283 variables, 49 binaries and 8,408
constraints per replan; summed C1 solve time is 13.5-15.8 seconds per case and
the reported MIP gap is zero/not applicable at optimum.

The flat `development_price_responsive` case reproduces the price-insensitive
reference physical quantities exactly. With NG at EUR 55/MWh LHV and central
efficiency 0.345, break-even is EUR 159.420290/MWh_e. The synthetic step has
84 executed hours at EUR 100/MWh_e and 84 at EUR 220/MWh_e: VN25 NG is zero
below break-even, uses 36,381.570836 MWh LHV above it and reaches but never
exceeds 350 MW. The 0.34 sensitivity has a EUR 161.764706/MWh_e break-even and
preserves its lower electricity-per-fuel conversion.

Both configurations annualise to exactly 6.75 Mt/y in every case. Material,
origin, carrier-WAG, steam, no-export, generator conversion and represented-
cost guardrails pass. IJ01 stays at zero modelled electricity and named NG;
its unresolved CHP conversion remains the accepted deferred-energy bucket.
The step case annualises VN25 NG to 6.829341 PJ/y and generator WAG plus flare
to 8.206983 PJ/y. Their 4.1 and 10.6-PJ/y MER values remain unforced
post-run anchors, so the differences are not fitted away.

That gate's decision was `development_VN25_price_response_ready`. VN25's zero-to-cap
hourly flexibility is explicitly an upper-bound development abstraction:
minimum load, startup/shutdown, ramping, outages and CHP/steam obligation are
omitted, not asserted to be zero. It permitted the separate governed DAM
price-data and forecast-contract task now completed below; it did not itself
authorise forecast-driven dispatch. DA bidding, settlement, export, revenue,
stochasticity, CVaR and mFRR remain unauthorised.

### Governed hourly D-D+4 point-forecast integration

Current status: pass. The run
`steel_s2_hourly_da_dplus4_point_forecast_integration_v1_20260720` uses the
external lineage `20260706_024807_lago_lear_six_year_benchmark`, model
`lear_lago_direct_dplus4_strict_no_future_1092` and feature variant
`LEAR_LAGO_DIRECT_DPLUS4_STRICT_NO_FUTURE`. Source fingerprints, run metadata,
origin, target, split, lead 0-4, local delivery day/hour and information timing
fail closed. Only `y_pred` enters optimisation; `y_true` is read after solving
for MAE/RMSE/bias, and MAPE is not used.

The same unified builder solves the mandatory price-insensitive benchmark, a
governed-flat responsive reference, an 80-EUR/MWh adapter parity case, seven
validation replans and one frozen seven-replan held-out window. Every case uses a 120-hour D-D+4 plan, executes 24 hours,
carries inventories and production credit/debt, and closes the seventh
cumulative production deadline exactly. All 70 C0/C1 models terminate
optimally with Gurobi. The maximum model size is 5,917 variables, 35 binaries
and 6,013 constraints; flat price and dispatch parity residuals are zero.
C0/C1 annualise to 6.75 Mt/y in every case, maximum reported material residual
is 0.000016 t and carrier-specific WAG residual is zero. Validation MAE/RMSE
are 29.033426/37.542358 EUR/MWh; held-out MAE/RMSE are
20.801968/26.974460 EUR/MWh over 840 forecast instances per split.
Against both the same-model flat case and the mandatory price-insensitive
benchmark, the held-out execution uses 886.962263 MWh more grid import,
221.372837 MWh more VN25 electricity and 1,767.960042 t/y more annualised
imported slab; represented executed procurement cost is EUR 2.130163 million
higher. Held-out VN25 fuel is 36,402.038087 MWh LHV carrier-specific WAG and
zero named NG; the validation case uses 37,523.582568 MWh WAG and zero named
NG. These are solved responses, not fitted anchors.

The first held-out integration exposed that the existing +/-0.5% rolling
envelope still allowed terminal production credit. The accepted correction
keeps intermediate credit/debt but imposes a hard equality on the aggregate
final 24-hour execution block, not on hourly throughput or route shares. The
superseded partial run is retained as
`steel_s2_hourly_da_dplus4_point_forecast_integration_v1_20260720__partial_terminal_quota_diagnostic`.

The decision is `ready_for_deterministic_DAM_price_response`. The next
permitted task is deterministic point-forecast price-response analysis against
the mandatory flat/price-insensitive benchmark. This does not authorise DAM
bids, settlement, export revenue, ETS, stochasticity, CVaR or mFRR.

### Deterministic price-response and matched-lineage anchor diagnostics

Current status: pass with partial temporal coverage. Run
`steel_s2_deterministic_price_response_anchor_diagnostics_v1_20260720` solves
six controlled weekly cases and 180 checkpointed held-out replans. Actual local
delivery-day durations give 4,321 executed hours, or 49.326% of 8,760; all
annualised ledgers are therefore labelled `partial_year_not_annual`.

The active objective hierarchy is production progress, represented procurement
cost, then the non-economic physical tie-break. All 444 C0/C1 models terminate
optimally; the largest has 5,966 variables, 35 binaries and 6,061 constraints.
C0 and C1 both close the cumulative 6.75-Mt/y trajectory at 3,329,537.671 t
over the observed support. Material and origin residuals are zero within
reporting tolerance, and separate BFG/COG/BOFG balances close. No residual
electricity, NG or material enters the model.

Flat adapter parity is 0.000000134 EUR on the complete first 120-hour plan.
On identical initial states, forecast-responsive represented cost weakly
dominates the flat comparator for C0/C1 on validation and held-out y_pred.
The separately labelled y_true oracle weakly dominates forecast dispatch on
realised cost in all four configuration/split comparisons. Operational runs
remain y_pred-only.

The same solved rolling lineage produces the physical and anchor ledgers. It
contains two primary-comparable Rank-1 generator rows, but neither is below
7.5%: VN25 named NG is 0.6985 versus 4.1 PJ/y and generator WAG plus flare is
7.0618 versus 10.6 PJ/y. This is an evidence/coverage gap, not a calibration
target. The decision was `price_response_valid_anchor_coverage_partial`. It
permitted the governed deterministic DAM-response interpretation now completed
below; it did not authorise bidding, settlement, revenue, ETS, stochasticity,
CVaR or mFRR.

### Source-driven deterministic D-D+4 thesis interpretation

Current status: complete. The governed interpretation is recorded in
`C5_SOURCE_DRIVEN_DETERMINISTIC_DPLUS4_INTERPRETATION.md` and uses four frozen
validation and four frozen held-out representative periods. It retains the
decision `source_valid_emulation_rejected`.

The result is configuration-specific. C0 response is mainly substitution of
selectively timed grid import for WAG-derived internal generation and reports
zero expensive-to-cheap load shift. C1 adds material-buffered DRP/EAF demand
timing and shifts 10.962 GWh/y in validation and 11.822 GWh/y held out on the
`representative_period_annualised` basis. Final product remains 6.75 Mt/y, all
336 rolling replans are optimal, and all 736 physical guardrails pass.

Whole-period strategy costs remain arithmetic only. Governed C1 ends with
4.340 kt more DRI inventory than flat operation in validation and 4.189 kt more
held out, so the EUR +63.612 million/y and EUR +46.542 million/y arithmetic
must not be described as adverse forecast value. The identical-state
first-planning-window oracle comparisons remain the only valid upper-bound
claim.

A post-review aggregate-only correction fixed the compact named-NG PJ-to-MWh
conversion by a factor of 1,000. The governed long-form ledger, cached cases,
physical model and solver results were unchanged; held-out governed C1 named NG
is 8.28557 TWh-LHV/y.

The source-driven interpretation gate is closed. Its next permitted use is
thesis-manuscript integration of this bounded result. Outside the separately
authorized overlay below, any later calibrated-emulation or economic-uplift
claim first requires source-backed PeFa consumption/inventory/terminal closure,
a terminal-inventory value bridge, and requalified genuinely independent
validation evidence.

### User-authorized full-site emulation overlay

Checkpoint 2 is repaired and pending reviewer re-review under
`steel_c5_user_authorized_full_site_emulation_v1_20260722`. The immutable
strict target and parameter contracts remain unchanged; separate overlays
freeze the accepted full-site anchors, explicit background-load cases and the
first bounded sensitivity ledger. The analytical design is limited to three
background shares crossed with nine one-family-at-a-time recipes (27
candidates) plus the immutable source baseline. Carrier yields never co-move
within an analytical candidate; at most one named process-electricity intensity
moves in the corresponding recipe. At most 30 candidates and five retained are
allowed. The active builder and closed-loop runner now expose an opt-in,
non-negative site-background electricity term with a zero default; explicit
WAG-only, named-NG-only and total generator electricity; gross import, zero
gross export and net-exchange identities; a separate reporting-only first-order
process-factor CO2 ledger; physically represented/full-site coverage shares;
and traceable prior/relaxed parameter-range exceptions. The historical
`wag_electricity_mwh` alias retains its total internal-offset meaning for
regression compatibility; new WAG-only interpretation uses the explicit
generator field. The first-order factors are BF 1.495 tCO2/t hot metal, BOF
0.0825 tCO2/t liquid steel, KGF 0.20 tCO2/t coke, sinter 0.248 tCO2/t sinter,
PeFa 0.105 tCO2/t pellets and EAF 0.126 tCO2/t liquid steel. The DRP 0.286
tCO2/t DRI capture stream is explicitly excluded from direct CO2. These
selected diagnostic factors are not Mode-B, ETS-ready or Tata truth. Execution
remains disabled pending reviewer approval; no candidate or governed annual run
has been created.

The one allowed repair cycle additionally enforces that selected-factor CO2
plus its visible constant cannot exceed the configured target, requires an
explicit valid named process for the electricity, NG and coking-input selection
rules, and permits separate C0/C1 background loads while retaining the scalar
zero-default fallback. A local-only one-replan Gurobi smoke comparison used the
governed flat fixed-reference cost configuration. Omitted background and
explicit zero were exactly identical for production, generator output and grid
import. The 5% case applied 18.0936073059 MWh/h to C0 and 27.9109589041 MWh/h
to C1; all six configuration solves were optimal, production changed by at
most 0.000002 t over the executed block, material/carrier and electricity
identity residuals were zero, export remained zero and cost reconciliation
passed. C0 responded with +239.129058 MWh internal generation and +197.035074
MWh grid import. C1 responded with -276.117903 MWh internal generation and
+877.869929 MWh grid import; this reflects an alternative feasible WAG/grid
allocation and a small represented-load timing change, while each case's gross
electricity identity remained exact. Temporary smoke outputs were removed and
are not governed lineage.

Checkpoint 3 then evaluated the immutable source baseline plus exactly 27
structured analytical candidates: 5%, 15% and 25% explicit background shares
crossed with the frozen nine one-family-at-a-time recipes. BF in C0 and EAF arc
in C1 were selected for the named electricity-intensity recipes by the
result-independent largest-baseline-represented-load rule. Six candidates were
rejected by explicit physical/bound checks and five were retained for review.
Gross electricity, WAG electricity, NG, first-order
CO2, C0 coal/material, source deviation, bridge size and physical penalties
remain separate score families. The retention-only repair now keeps
`source_driven_baseline`, the boundary-only control
`bg25_central_no_movement`, the dose control `bg15_central_no_movement`,
`bg25_single_process_electricity_high` and `bg25_cog_yield_high`.
`bg25_bfg_yield_high` and `bg25_bofg_yield_high` are excluded as strictly
dominated by the retained COG-high response. This retention is analytical triage only and
does not authorize promotion, rolling execution or calibration claims.

Checkpoint 4 subsequently solved all five retained candidates for the two
governed development weeks: 30/30 cases completed, 420/420 solver models were
optimal and every physical gate passed. The cache-only independent review is
`complete`. The frozen Badarinath relationships BF6 > BF7 and positive DRI
storage correlation failed for every candidate, while HSM > DSP throughput,
expensive-hour EAF reduction and oracle dominance passed. The five-candidate
and two-repair stop rules were reached; only the source-driven baseline and
`recovery_bg25` reviewed comparison pair continued to the separately governed
held-out evaluation. Phase 5C later establishes that those two historical
Badarinath checks were misdefined: the BF statement was not an absolute-
throughput ordering and Table C.6 correlated hourly changes in storage level,
not storage level. This reclassification does not change the historical run or
its candidate selection.

Checkpoint 6 then completed all 48 candidate/week/strategy rolling cases over
the independently selected eight-week TEST set, with 672/672 optimal solver
models. Independent review is `complete`. The 24 raw duration-aware
fixed-background flags are preserved in the run ledger and classified as
`serialization_false_positive_reviewer_disposition`: their approximately
0.00412-MWh/y residual is 5.2e-9 relative, so the material physical failure
count is zero. The source-driven baseline remains central; `recovery_bg25`
remains `emulation_sensitivity_only` and nonpromoted. Results are weighted
annual equivalents from representative held-out weeks, not an annual backtest.
The next bounded thesis gate is terminal-inventory equivalence and a
terminal-inventory value bridge before any economic-uplift claim.

The bounded Phase-3 operation/route robustness audit
`steel_c5_phase3_operation_route_robustness_v1_20260727` then used only the
calm and volatile DEVELOPMENT weeks. It completed the fixed cap of six rolling
cases, 12 C0/C1 trajectories and 84 models with no implementation failure.
The free-route reference and the source-informed 45-55% BOF-share band passed
both weeks. Their realised C1 BOF shares were approximately 50.75-50.82%, so
the band did not materially displace the accepted endogenous route. Forcing
the exact 50.3703704% BOF ratio made all seven C1 replans infeasible in both
weeks while the paired C0 replans remained optimal; this is retained as a
physical robustness finding, not a task failure or calibration target.
BF6/BF7 central behaviour was reported, but BF capacity/rate perturbations
were not run because the active runner exposes no permitted override without
changing the model builder or canonical inputs. The run is diagnostic,
nonpromoted and makes no economic-uplift claim. The next gate therefore
remains terminal-inventory equivalence and a defensible terminal-value bridge.

The bounded Phase-4 DEVELOPMENT terminal-equivalence diagnostic
`steel_c5_phase4_terminal_inventory_equivalence_v1_20260727` closes under
outcome B. The calm price-insensitive reference completed all seven C0/C1
replans and froze nine carried states at executed hour 167: coke, sinter, hot
iron and cold slab for C0/C1, plus C1 DRI. The reference target residuals are
exactly zero under the shared 1-t terminal-state policy. With identical frozen
inputs and free C1 routing, adding only the final executed-hour target made the
governed C0 model solver-proven infeasible; the target, production quota and
physics were not relaxed. The oracle and second DEVELOPMENT period were not
run after this structural comparability failure. No cost comparison, value
captured, annualisation, held-out evaluation or promotion conclusion is
authorized. Because inventories are unpriced in the represented procurement
objective, the next gate is a source-backed, non-duplicated inventory-value
bridge or a separately authorized strategy-neutral terminal contract; neither
is currently accepted.

The v2 follow-up is retained as a structural diagnostic: it activated the
fixed 1% band at the first 120-hour-visible endpoint but left the builders'
cyclic horizon-end inventory equalities active. At replan 2 this literally
required inventories to equal their replan starts and simultaneously lie near
the campaign target. The later cold-slab failure arose because independently
horizon-scaled route bands were reset at each replan. Neither failure proves
that the frozen band is physically unreachable.

The corrected DEVELOPMENT gate
`steel_c5_phase4_reachability_aware_terminal_band_v3_20260727` resolves both
conflicts without widening or tuning the band. The price-insensitive run is
both the pre-responsive target selector and reference comparator. Responsive
plans remain ordinary D-D+4 plans while the endpoint is farther than five
days away; once visible, their horizons end at the campaign endpoint (120,
96, 72, 48 and 24 hours), the terminal band replaces cyclic inventory
equalities, and route-output bounds are expressed as cumulative campaign
progress net of already executed output. All six cases and 84/84 C0/C1 models
are optimal; all 54 state comparisons pass with zero band excess and maximum
absolute target deviation 121.048 t. Physical, accounting, activation and
non-anticipativity checks pass.

The authorized DEVELOPMENT cost comparison reports governed savings versus
the price-insensitive reference of EUR 0.117m/0.259m (February C0/C1) and EUR
0.544m/0.844m (July C0/C1). Governed value captured relative to the oracle is
70.7-82.1%. These are represented-procurement results over two selected
DEVELOPMENT weeks, not annualized uplift or held-out evidence. A value bridge
is not required for this accepted 1% operational-equivalence comparison; it
would be required only to assign monetary value to residual within-band state
differences.

For week, month and year campaigns, the same rolling design remains bounded:
cumulative production and route progress use actual executed hours relative to
the campaign quota, while terminal inventory control activates only when the
endpoint enters the five-day physical horizon. The model therefore need not
foresee the full month or year, but each executed block preserves the cumulative
production/route position needed to finish the campaign. Phase 5A independently
reviewed the integrated anchors and authorized exactly one paired Phase 5B C0
export sensitivity. The original v1 attempt failed closed in February replan 3
because the sale-state reconstruction preserved total executed final product
and four inventories but omitted the cumulative BOF, HSM and DSP quantities
used to recompute later route-deadline bounds. The export trajectory had
executed 52.369865 t more HSM output before replan 3, which lowered its 72-hour
HSM upper bound from 43,843.954722 t to 43,791.584857 t; the captured no-export
incumbent saturated the former and therefore appeared to violate the latter by
exactly 52.369865 t. This was not a physical infeasibility.

The corrected exact preservation schema v4 adds executed BOF liquid steel,
HSM final output and DSP final output to the five existing production/inventory
states. The isolated containment clone still fixes shared variables at full
precision, export at zero and uses the unchanged canonical 1.0-t acceptance
tolerance. No physics, price, terminal band, production target or export-
economics input changed. The governed rerun
`steel_c5_phase5b_c0_export_sensitivity_v2_20260727` completes February before
opening July: 4/4 trajectories and 56/56 C0/C1 models are optimal; all 14
containment records and their eight-state preservation audits pass; physical
override fingerprints match; and maximum terminal-band excess is zero.

The substantive Phase 5B test still stops. February adds effectively zero WAG
electricity (0.000000000521 TWh_e/y annual-equivalent) and July adds 0.010975
TWh_e/y, so both remain below the frozen 0.015014-TWh_e/y material threshold.
Gross grid import also increases by 2,262.481785 MWh and 1,868.070864 MWh,
respectively, failing `gross_grid_import_weakly_nonincreasing` in both weeks.
Although represented net cost falls by EUR 26,376.81 and EUR 42,433.65 after
export revenue, these are DEVELOPMENT results and do not override the failed
physical/economic guardrails. Decision
`phase5b_threshold_or_guardrail_failed_retain_and_freeze_no_export_central`
therefore freezes the no-export central model. At the Phase 5B gate, held-out
validation, export, bidding, settlement, ETS, stochasticity, CVaR and mFRR
remain NO-GO; the later Phase 5C source adjudication supersedes only the held-
out next-gate decision.

The follow-up governed breakthrough run
`steel_c5_phase5b_breakthrough_tests_v1_20260727` tests whether February could
meet the same material threshold under a deliberately generous physical
endpoint: it maximises executed WAG-generator electricity, retains the corrected
eight exact comparator states and all frozen physics/targets/bands, and caps
each execution block's gross grid import and named NG at the no-export values.
Both trajectories and all 28 C0/C1 models are optimal; 7/7 sale-containment
records, resource caps and endpoint best-bound audits pass. The maximum is
42,670.959101366 MWh versus 42,670.959101443 MWh for no-export, a
-0.000000077-MWh numerical difference and therefore no physical upside toward
the +287.939726-MWh weekly threshold. Under the predefined gate, the clean
economic branch and July were not run. This test adds no ETS cost, export-price
floor, bid/ask spread, fee, imbalance charge or settlement rule. Those missing
market frictions make the earlier frictionless export economics optimistic, not
conservative, and cannot overturn the physical no-uplift result.

Phase 5C then returns to the primary source definitions without another solve.
`steel_c5_phase5c_source_mechanism_adjudication_v1_20260727` verifies that
Athanasiadis prices accumulated CO2 and represents WAG use with a negative
marginal-cost term. These are economic-boundary precedents, not an electricity-
export definition and not authorization to add ETS or a WAG credit to an
incomplete marginal-emissions boundary. The earlier Badarinath DRI check used
inventory level; the source's Table C.6 uses changes in storage level. Pearson
correlation between same-hour governed price and hourly DRI-inventory change is
+0.289352 in February and +0.293885 in July, so the corrected direction passes.
The earlier BF6 > BF7 absolute-burden check is also retired: after normalising
each furnace by its own represented capacity, BF6/BF7 loading is 76.630%/
77.676% in February and 77.030%/77.415% in July. This does not reproduce the
source's asset-specific efficiency claim, because separate public BF output and
nameplate denominators remain unavailable. It is therefore `not_comparable`,
not a parameter-fitting invitation. No physics, objective, terminal contract,
price or source-driven parameter changes. The no-export model remains frozen,
and a separately governed frozen terminal-aware held-out validation is now the
next authorised gate.

The subsequent bounded DEVELOPMENT-only C0 mechanism experiment keeps the
accepted physical interface structurally invariant and leaves the held-out
weeks untouched. Its 15 cached cases contain 210/210 optimal models. Lower NG
activates named generator NG in the two volatile cases but not in the calm
case. Because the builder tie-break penalizes flexible-heat NG but not
generator NG, zero flexible NG is an allocation-location non-identifiability,
not proof of no substitution. Small realised WAG-generation spreads are
endogenous-dispatch diagnostics, not parameter drift. The source-driven
baseline remains central, all repair candidates remain nonpromoted, and the
stop rule authorizes no second search.

Phase 5D reopens only the separately governed user-authorized emulation layer.
The source audit screens out forced C0 NG shares for HSM, PEFA, boilers and
generators because no plant-specific C0 evidence supports them. It instead
uses Athanasiadis's mandatory secondary-load architecture and the already
accepted normal-case interpretation to select one transparent operating
policy: the conserved 3.07-PJ-LHV/y flexible other-site heat service receives
1.65 PJ-LHV/y NG and 1.42 PJ-LHV/y WAG. The strict endogenous default remains
available and unchanged.

The governed DEVELOPMENT pair
`steel_c5_phase5d_source_backed_ng_mechanism_closure_v1_20260727` passes
February before opening July. All 28 C0/C1 models are optimal and all rolling,
terminal, production and carrier checks pass. Named C0 NG becomes 9.655
PJ-LHV/y in both weeks, only 0.011 PJ/y or 0.114% below the 9.666-PJ/y real-site
anchor. The policy displaces WAG from the flexible service into useful internal
generation: WAG electricity increases by 0.158125 TWh_e/y in February and
0.129274 TWh_e/y in July, while executed grid import falls by 3,032.534241 MWh
and 2,477.083718 MWh. Total WAG generation changes by at most 0.000605 PJ/y.
The July HSM/DSP mix shifts by +170.558/-170.558 t but remains within 1% of the
comparator and preserves total production and all terminal bands.

This policy is deliberately non-endogenous and is retained as a historical
user-authorized sensitivity. Phase 5E supersedes its promotion because 8.005
of the 9.655 PJ/y result is still the anonymous fixed full-site component. It
is not evidence of a measured plant burner split and is not the annual C0 NG
account used after Phase 5E.

#### Phase 5E source-backed annual boundary closure

The official 2025 MER detail study supplies exact locators and complete annual
partitions. C0 NG is 12.5 PJ/y: 1.5 ironmaking, 9.1 steelmaking/rolling and 1.9
Vattenfall. C1 NG is 46.7 PJ/y: 2.0 existing ironmaking/energy, 13.1 existing
steelmaking/rolling, 3.8 Vattenfall, 27.7 DRI and 0.1 EAF. The former 9.666-PJ/y
C0 comparison is superseded as the primary real-site anchor. Athanasiadis
remains secondary.

The broader MER electricity totals are 13.7 PJ/y in C0 and 17.8 PJ/y in C1.
Named operating categories explain 11.4 PJ/y (83.2%) and 16.2 PJ/y (91.0%);
the visible 2.3/1.6-PJ boundary remainder is derived only from two independent
MER totals and never enters dispatch. Scope 1 source classes explain 100% of
the 12.6/8.3-Mt totals within source rounding. Coal is compared primarily on
the official 120.8/58.0-PJ energy basis; the older 3.66-Mt mass comparison
remains definition-unresolved and is not used to change coke or coal inputs.

The C0 generator source balance is 23.6 PJ WAG plus 1.9 PJ NG to 9.8 PJ
electricity and 15.7 PJ balance/losses. C1 is 10.3 PJ WAG plus 3.8 PJ NG to
5.9 PJ electricity and 8.2 PJ balance/losses. Fuel-proportional reporting
therefore gives 2.519 and 1.197 TWh/y WAG electricity, within 0.34% and 2.67%
of the secondary 2.528/1.23-TWh/y anchors. This attribution is not forced into
hourly dispatch.

The governed run
`steel_c5_phase5e_source_backed_anchor_closure_v1_20260727` passes 14/14
primary annual families and every carrier-coverage and generator-balance gate.
A fresh February no-export solve passed before July opened; all 28 models and
24 dynamic checks pass. HSM and PEFA heat remain explicitly WAG-supplied,
C1 DRI remains locked at 9.9 GJ-LHV/t DRI, production/terminal/carrier/steam
checks pass, export stays zero and the corrected positive DRI inventory-change
price direction is preserved.

The annual accounts are fixed source-backed service partitions. They are not
added to optimizer flows, priced, or presented as hourly plant schedules.
Direct overlaps are reported separately, and the legacy 8.005-PJ solver field
is explicitly excluded from the Phase 5E full-site total. Phase 6 design is
GO; execution remains NO-GO pending frozen held-out dynamic validation.

#### Phase 5F HSM controller and HERACLES blocker evidence

The completed HSM controller makes the QRA COG/NG mixtures the default
development abstraction in 24-hour blocks: C0 is 55%/45% COG/NG by volume and
C1 is 20%/80%. BFG and BOFG remain excluded. Explicit C0 HSM NG displaces the
anonymous NG component hour by hour. February passes before July opens; all
28 C0/C1 rolling models pass. WAG production remains approximately 57.352
PJ/y, while released WAG is exposed through additional generator use or flare.
This is an allocation result and not authorization to change WAG yields.

`C5_HERACLESS_BLOCKER_EVIDENCE_GATE.md` verifies all 124 pages of the definitive
technical Part B and refines `STEEL-SC-0016`/`WD02`. HERACLES directly confirms
that VN25 85%/IJM-01 15% is time in operation, that VN25 uses available
production gases before NG top-up to an unspecified minimum fuel need, and
that WBW2 needs more NG as COG declines. It supports later bounded DRI/EAF
transition, bypass, maintenance, cold-DRI and steam tests and records the
83,400-m3 oxygas-holder geometry. It does not prove the QRA shares, a 24-hour
HSM timescale, a VN25 minimum rate, usable gas-store energy, full WAG/steam
allocation or BF6/BF7 comparability. All added register rows are non-executable.
Model freeze and Phase 6 execution therefore still wait for the separately
frozen terminal-aware held-out dynamic validation.

#### Phase 5G baseload integration and final deterministic freeze attempt

Phase 5G replaces exact residual closure with explicit source-component overlap
mapping and attempted constant site baseloads. The baseline and selected-
baseload validation each solve 56/56 terminal-aware rolling models. All 194
physical checks pass, including additive constant NG, procurement identity,
zero legacy bridge, unchanged HSM policy, unchanged WAG production, electricity
balance, steam and terminal handoff. The DRI 8.1 + 1.8 = 9.9-GJ/t NG split,
0.3-GJ/t electricity value and validation-only outage/85:15 interpretations
also pass.

The validation rule selects 90% for electricity and 90% for NG. Electricity
errors improve from 42.59% to 10.05% in C0 and 31.17% to 3.20% in C1; C1 NG
improves from 27.98% to 2.64%. C0 NG fails: its error rises from 64.00% to
90.33% because the electricity baseload induces about 12.1542 PJ/y of generator
NG in addition to the 7.1998-PJ/y NG baseload. This is a real cross-carrier
response rather than an accounting duplicate.

Decision is `baseload_selection_gate_failed_model_not_frozen`. The attempted
contract stays `selected_validation_failed_not_promoted`; the governed run
stops at 112 models and admits no held-out result. An earlier local
orchestration defect opened the old held-out scratch cases prematurely; they
are excluded and cannot support a pristine claim. No reselection used them.
A revised, separately approved gate must score electricity and NG jointly and
use new unseen held-out periods. Until then the deterministic model and Phase 6
execution remain blocked.

#### Phase 5H four-residual effect and final-selection gate

Phase 5H adds zero-default constant residual-steam and reporting-only residual-
direct-CO2 interfaces and governs electricity, NG, steam and direct CO2 in one
non-overlapping source-service contract. Athanasiadis Figure 38 and its adjacent
equations verify the existence and constant modelling role of all four terms,
but publish no Tata-specific magnitudes.

The mandatory steam evidence gate fails. No public source establishes a normal-
operation residual-steam maximum with pressure/enthalpy, annual operation,
condensate-return and explicit-load overlap bases. The HERACLES approximately
50-t/h value is startup-only; nameplate boiler capacity, steam spill and the
retired 9-PJ value are prohibited substitutes. Therefore the steam sweep,
electricity/steam interaction, selected validation and newly frozen held-out
validation do not open. The four-residual contract is not promoted and the
decision is `four_residual_gate_failed_residual_layer_not_promoted`.

The bounded electricity/NG/direct-CO2 diagnostic completes 560/560 models. Only
10% electricity remains source-compatible; 20-90% make C0 generator NG exceed
the 1.9-PJ/y MER component. The 10% case reduces C0 WAG flare from 8.533 to
7.146 PJ/y, but electricity errors remain 38.97%/28.06% in C0/C1. Conditional
90% NG and 90% CO2 shares reduce NG errors to 6.39%/2.68% and CO2 errors to
1.44%/1.60%, but would add roughly EUR 109.8/180.4 million/y of NG cost. Those
large aggregate shares are not physical identification. Scope 2,
captured/avoided CO2, ETS and overlapping process counters remain excluded.
All residual interfaces stay inactive, the process/HSM model is retained, the
deterministic model is not frozen, and Phase 6 execution remains blocked.

#### Phase 5I electricity-only represented-boundary freeze

Phase 5I supersedes the Phase-5H all-or-nothing residual conclusion only for
the independently source-compatible 10% electricity row. It promotes exact
constant loads of 15.707829645182 MWh/h in C0 and 17.538616398437 MWh/h in C1;
NG, steam and direct-CO2 residuals remain zero. The four predeclared fresh
held-out periods open once, with no reselection. All 56 models and physical,
terminal and component-overlap checks pass. C0 generator NG is 0.109457 PJ/y
against the 1.9-PJ/y MER component. Held-out electricity errors are 38.97% and
28.06%; these are representative-period generalisation evidence, not exact
annual backtests.

Decision is `represented_boundary_deterministic_model_frozen_for_phase6`.
The claim covers the represented physical and procurement boundary, not a
full-site digital twin, exact annual anchor replication or ETS-ready emissions.

#### Phase 6A deterministic DA handoff

Phase 6A converts the point-forecast net grid-import schedule into a
price-taking purchase-quantity bid and settles the fully accepted quantity at
realised DA prices. The flat EUR 80/MWh schedule is the mandatory
price-insensitive benchmark. The realised-price solve is an isolated,
never-submitted perfect-foresight oracle. All 168 evaluated models, 408 physical
checks and 13 timing/accounting checks pass. Relative to the flat benchmark,
the point-forecast schedule lowers represented four-period settlement cost by
about EUR 0.051 million in C0 and EUR 3.208 million in C1; oracle regret is
about EUR 0.032 million and EUR 0.373 million.

Three missing July-2025 realised hours are supplied by a fingerprinted
Fraunhofer ISE Energy-Charts supplement after its other 21 daily observations
match the governed source exactly. It is allowed only in settlement and the
oracle; the forecast parquet and executable `y_pred` information set are
unchanged. Decision is
`phase6a_deterministic_da_bidding_and_settlement_validated`. Phase-6B hourly
and bounded Phase-6C QH risk-neutral execution are now validated; CVaR has not
started.

#### Phase 6B hourly stochastic DA bid--clear--redispatch

Phase 6B replaces the quantity-only bridge with a frozen sixteen-tier purchase
ladder. H-point and risk-neutral H-S10 optimize non-negative incremental volume
per tier over D--D+4; every scenario sees the same bid curve. Actual prices are
loaded only after the D curve is submitted, only D is cleared and settled, and
the physical redispatch must consume the cleared import exactly. Price-
insensitive and configuration-matched true-PF trajectories use the same grid,
physics, settlement and terminal accounting.

The rolling state now carries all finite inventories, total production
progress and cumulative BOF/EAF/HSM/DSP/imported-slab route progress. When the
fixed week endpoint enters the look-ahead, the horizon truncates to
120/96/72/48/24 hours and the shared 1% terminal inventory band replaces the
cyclic horizon equalities. The band is selected once from a flat EUR 80/MWh,
price-insensitive run before responsive results are evaluated.

The accepted governed run is
`steel_phase6b_hourly_da_bid_clear_redispatch_a03_20260730`. It covers the
27-April-2026 normal day and 27-April--3-May rolling week for C0/C1 and H-point,
H-S10, price-insensitive and true-PF. All 256 checks and all 156 solves pass;
the maximum cleared-import redispatch residual is `2.87e-8 MWh`, export is zero,
and PF dominates every matched executable strategy. A03 is exactly cost- and
production-identical to a02; it supersedes a02 only by adding unambiguous
fixture keys. These are engineering fixtures, not economic evaluation or
tuning evidence. Phase 6C is the bounded QH successor; long-support runs, CVaR
and mFRR remain later gates.

#### Phase 6C quarter-hour stochastic DA bid--clear--redispatch

Phase 6C uses the same bid, clearing, redispatch, production-progress and
represented-cost chain on an explicit `dt=0.25` grid. A 120-hour plan contains
480 intervals and D execution contains 96. Interval flow quantities, fixed
services and rate bounds are scaled once; daily commitments remain daily,
24-hour mix blocks contain 96 intervals and physical-hour deadlines are mapped
to aligned interval indices. Historical fixed-hour schedules are rejected.
The hourly `dt=1` normal-day reference is reproduced with less than EUR `2e-9`
cost error and zero production error.

The accepted run
`steel_phase6c_qh_da_bid_clear_redispatch_a01_20260730` covers only the matched
27-April--3-May 2026 week. It executes QH-point, QH-S10, price-insensitive and
true-PF for C0/C1 using frozen hourly terminal bands. All 112 models and every
lexicographic tier are optimal; 203/203 gates pass. There are 86,016 submitted
bid rows, 5,376 realised redispatch intervals and 56 exact state handoffs. Each
trajectory produces approximately 129,452.054795 t and ends at 168 hours, 672
intervals and `2026-05-03T21:45:00+00:00`.

The compact comparison is descriptive, not annualised. QH-minus-hourly
represented cost ranges from EUR -29,145 to -330,868 across the eight matched
rows. This combines QH price signals and QH physical flexibility; it does not
identify forecast-shape value. QH-S10 p05--p95 coverage is 74.27%. Missing
plant-specific QH ramp/start/minimum-load/outage/CHP inputs make the QH
flexibility result an upper bound. Long-support evaluation, CVaR and mFRR
remain later gates.

#### Phase 5J corrected WAG-electricity closure

Phase 5J identifies a narrow objective/accounting defect: aggregate C0
generator NG was costed only when the retired full-site NG bridge was active.
After separating those activation conditions, increasing the electricity
baseload no longer induces implausible C0 NG generation while usable WAG is
flared. Across the validation sweep, the 90% candidate lowers C0 flare from
8.475 to 0.542 PJ/y, while C0 generator NG remains zero.

The shared 90% candidate gives validation electricity-anchor errors of 10.05%
in C0 and 3.20% in C1. A single 5% uniform WAG-yield reduction is rejected: it
only lowers C0 flare from 0.542 to 0.468 PJ/y while increasing grid purchase,
so it does not identify the remaining carrier-specific timing mismatch.

All 56 fresh held-out models and native physical checks pass. Held-out
electricity errors are 10.05%/3.20%, generator NG is 0.000/0.0125 PJ/y, and
flare is 1.059/0.247 PJ/y for C0/C1. C0 therefore fails the predeclared
1.0-PJ/y absolute flare gate. The threshold is not relaxed after held-out and
the share is not retuned. Phase 5I is superseded and Phase 6B is blocked; a new
gate requires an explicit source-backed carrier-buffer or gas-holder operating
contract rather than another annual baseload or WAG-yield calibration.

#### Phase 5K final user-authorized represented-boundary freeze

Phase 5K is the explicit methodological decision that supersedes the Phase-5J
failure. A carrier audit confirms that the C0 mismatch is concentrated in COG
and finds no source-backed correction to the generic yield coefficients. The
predeclared fallback therefore applies a C0-only 0.95 multiplier, clearly
classified as user-authorized rather than observed. C1 yields are unchanged.

The frozen contract combines that fallback with the already selected shared
90% electricity baseload, 7 PJ/y of constant site NG in both configurations,
zero residual steam and a common 2.0 MtCO2/y reporting-only direct-emissions
term selected from the validation-only 0.5-Mt grid. The NG load is external,
inelastic, non-WAG-displaceable and costed once. Its combustion emissions are
part of explicit NG emissions before the common CO2 term is added.

All 112 Phase-5K validation and fresh-held-out models pass. Held-out electricity
errors are 10.05%/3.20%, NG errors 8.46%/12.29%, WAG errors against direct
carrier sums +3.00%/+1.39%, and direct-CO2 errors 4.04%/5.08% for C0/C1. C0
flare falls to 0.080 PJ/y and C1 flare to 0.002 PJ/y. No held-out reselection
occurs. Decision is
`user_authorized_represented_boundary_deterministic_model_frozen_for_phase6`.

The Phase-6A rerun on the Phase-5K fingerprints passes 168/168 evaluated models
and all timing/accounting checks. Point-forecast bidding saves EUR 2.082 million
in C0 and EUR 4.679 million in C1 versus the price-insensitive comparator over
the four held-out 168-hour periods. Oracle regret is EUR 0.309 million and EUR
0.497 million. Decision is
`phase6a_phase5k_deterministic_da_bidding_and_settlement_validated`; Phase-6B
scenario-contract design is next, with execution still gated on probabilities,
non-anticipativity and an expected-value benchmark.

#### Phase-1 accepted boundary freeze

The Phase 5E annual source contract has explicit precedence over older user-authorized
analytical-screen classifications; it does not modify the immutable strict
source-ranked contracts. Historical 5/15/25% cases remain documented, but
active C0 background classes are 25% low, 30% central and 31% high, with
35-40% excluded absent new Tata evidence. Primary gross electricity is
3.154-3.170 TWh/y; Athanasiadis Table 8 at 3.17 TWh/y is model context.

The primary generator anchor is 2.528 TWh/y of WAG-only electricity, excluding
NG-generated electricity. Separate model precedents are approximately 2.74
TWh/y from Table 8 and 2.773 TWh/y from the Figure-91 interpretation. All NG
boundary rows use PJ_LHV/y and an annual-calendar basis: 8.005 PJ/y fixed,
0-3.07 PJ/y flexible-heat NG allocation within the unchanged 3.07-PJ/y total
WAG-plus-NG service, 9.666 PJ/y primary real, and approximately 10.35/10.425
PJ/y Figure-91/Table-8 context. No residual percentage or plug is permitted.

Total WAG remains approximately 57.3-57.5 PJ/y against approximately 54 PJ/y
MER/Tata context (approximately +6%); WAG yields and runtime coefficients are
frozen. A 1.7-2.0-MtCO2/y site-boundary bridge is reporting sensitivity only,
separate from represented Mode-B/marginal emissions, and may not affect
dispatch, optimization or cost. Anchor deviations are preferred within 5%,
may be accepted at 5-10% only with physical and methodological credibility,
and require an explicit boundary/configuration explanation above 10%; improving
one anchor by materially worsening several others is prohibited.

The Phase-0 v6 diagnostic passes 8/8 trajectories and 56/56 endpoints. Across
the four frozen DEVELOPMENT cases, the certified WAG-electricity outer maxima
are 2.229431, 1.935251, 2.230099 and 2.056505 TWh/y, all below 2.528 TWh/y.
No candidate is promoted. Phase 2 is GO only as the next bounded improvement
step under these frozen classifications; it is not permission for calibration,
candidate search, export, price, route-share or physical-parameter changes.

#### Phase-2 validation-tolerance contract

Phase 2 uses the centralized
`steel_unit_purpose_validation_tolerance/v2_20260727` contract. This changes
validation acceptance and evidence only; it does not loosen a Gurobi
feasibility tolerance, modify a physical equation, change an objective or
alter the frozen Phase-1 inputs. Cumulative production, deadline, carried and
terminal-state comparisons allow at most 1 t. Frozen price inputs are compared
by exact fingerprints. Hourly money identities allow EUR 0.01, while a
trajectory/year cost reconciliation independently allows
`max(EUR 1, 1e-8 * comparison scale)`. Electricity and material balances keep
their small unit-specific tolerances, and binaries remain strict.

The six registered per-trajectory electricity guardrails keep an exact
governed tolerance of `1e-6 MWh_e`. Their threshold comparison may separately
accept no more than 256 binary64 ULPs at the comparison scale (with scale floor
one) as non-accumulating roundoff. The raw residual, governed tolerance,
positive excess, ULP allowance/method, normalized residual and status are all
machine evidence. This is not a doubled tolerance, a solver-feasibility change,
or an hourly/trajectory accumulation rule; `1e-6 + 1e-9 MWh_e` remains a fail,
and an unknown threshold purpose fails closed.

Tolerance is never accumulated across hours, constraints or replans. The C0
sale-containment validation solves an isolated clone, fixes shared incumbent
variables at full precision and export at zero, and may add only registered,
bounded production/deadline/terminal validation slacks. The exact executed-
block terminal quota equality `rolling_production_terminal_quota_equality` and
the explicit in-horizon cumulative deadline equality
`rolling_production_future_terminal_quota_equality` are registered in that
cumulative production class. These are two literal registrations, not a name
pattern, and do not cover any balance, capacity or economic row. Every active row is
reported with raw residual, allowed tolerance, used relaxation, normalized
residual and pass/fail; an unknown family fails closed. The original model must
retain an identical fingerprint and repeated validations must not accumulate
components or relaxations. New S4/C5 runners must import the contract; the
hashed pre-existing runner inventory is an explicit legacy exemption, not a
precedent for new hard-coded comparisons.

The one authorized full-matrix source attempt may not be rerun or rewritten.
Its narrowly authorized posthoc guardrail re-audit is a zero-solve,
identity-scoped diagnostic: it binds the source summary, guardrails, case and
solver tables, implementation, config and authorization metadata by hash;
retains the original source status as failed; and may supersede only guardrail
interpretation in a new local attempt. It does not change physical/economic
results, promote a candidate or make a held-out, settlement or market claim.

This reopening does not authorize an exact digital-twin claim or combine the
physical fuel/oxidation CO2 ledger with the first-order full-site ledger. The
Tata questionnaire remains outside this calibration workstream.

## 7. Explicit no-go items

The physical, fixed-reference S2, governed point-forecast integration and
deterministic response diagnostics pass. The accepted baseline remains separately
price-free and no-export. The corrected one authorized Phase 5B export
sensitivity completed but failed its threshold and gross-import guardrail, so
the no-export central model is frozen. Do not add:

- a static C0 hour calendar or fixed production profile;
- fixed C0/C1 route shares chosen to make the model feasible;
- residual electricity, NG, coke, slab or WAG as hidden supply;
- aggregate/mixed WAG physical allocation, a fixed WAG/NG ratio or Wobbe in
  the central physical model; the Phase 5D split is historical sensitivity-only,
  while Phase 5E annual source accounts do not enter physical allocation;
- reinterpretation of the VN25 85%/IJM-01 15% operating-time statement as an
  output or fuel split, or of the HSM 24-hour development block as source truth;
- conversion of the 83,400-m3 oxygas-holder geometry into energy or of
  transition-only DRI/BF minima into universal normal-operation constraints;
- aggregate process CO2 plus Mode-B fuel CO2 in one total;
- ungoverned prices or live-market operation; DA price--quantity bidding,
  settlement and risk-neutral S10 stochasticity are authorized only inside the
  validated hourly Phase-6B runner and bounded matched-week QH Phase-6C runner,
  while long-run evaluation, generator export revenue, ETS, mFRR, CVaR and
  product revenue remain blocked;
- a public-anchor-fitting objective or parameter choice in the immutable strict
  source-driven baseline; the separate user-authorized emulation overlay is
  governed by its own explicit contracts and sensitivity labels.

## 8. Historical and conflicting documents

The following preserve useful negative diagnostics but are not active C0
policy sources:

- `C5_C0_CONFIGURATION_MATCHED_ANNUAL_AUDIT_GATE.md`;
- `C5_C0_SCHEDULE_AND_DENOMINATOR_SOURCE_GATE.md`;
- `C5_CANONICAL_C0_C1_PHYSICAL_BASELINE_REPORT.md`;
- `run_s4_4c5p_ba_c0_fixed_schedule_reporting.py` and associated runs;
- fixed-profile C3/C4/C5p_e accounting reports.

When an older report conflicts with this roadmap or `PROJECT_DECISIONS.md`,
retain it as historical lineage and continue from the active baseline. Do not
re-run or repair the static schedule unless the task explicitly audits history.

## 9. Repository-maintenance rule

Update this document when the active entrypoint, accepted baseline, boundary
status or next gate changes. Do not create another general C5 model-state,
handoff, canonical-baseline or roadmap markdown file. Asset-specific reports
may exist only when they close a named gate and must link back here.

Generated run outputs belong under `data/03_Optimisation/runs/` under the run
contract. Small source/governance registers belong under the existing S4 input
asset structure. Neither should be presented as a new source-of-truth document.
## Performance-interface note (2026-07-30)

The active deterministic rolling path now defaults to
`performance_mode: optimized_equivalent`. It shares the governed profiler,
structural-signature and cache schema with hydrogen, while retaining its own
physical builder. Validated immutable input tables and fingerprints are cached;
the Pyomo model is still rebuilt and cross-replan warm start remains a safe
cold fallback because no index/state mapper has yet passed parity.

The final two-replan diagnostic (`20260730_optimized_equivalent_a02`) passed
56/56 physical-ledger parity checks exactly. Median C0 and C1 speed ratios were
0.97x and 1.08x relative to legacy, both inside the 10% non-regression gate.
This is non-canonical performance evidence and changes no physical parameter,
stage gate or deterministic research conclusion. Any future stochastic steel
runner must reuse `OPTIMISATION_PERFORMANCE_CONTRACT.md`; this note does not
authorise stochastic steel development.

## Representative D-only quarter-hour study gate (2026-07-31)

The accepted forecasting audit is
`20260731_donly_family_audit_s10_s30_v3`. It compares the frozen Strict LEAR,
LEAR FS3 and XGBoost FS3 point models on exactly 307 common D-only test origins
and regenerates all scenario paths with the same validation-residual pool,
raw-400 to S30 reduction and nested S10 construction. Strict remains frozen for
the main experiment; no four-week reselection or family fallback is permitted.
Strict test MAE is 20.390 EUR/MWh and rMAE versus the DST-aware previous-week
naive is 0.619. Its S10 50/80/90% coverage is 50.1/76.4/84.2%; undercoverage is
reported and does not trigger evaluation-set recalibration.

The accepted input run is
`20260731_four_regime_inputs_s10_s30_v11`. The additive QH overlay preserves
every hourly point, scenario and actual anchor to at most `5.7e-14` EUR/MWh.
On all 55,664 true held-out QH rows, including observations down to
-499.62 EUR/MWh, shape MAE/rMAE improve from 32.749/0.853 to 31.995/0.833;
ramp MAE improves from 13.567 to 10.059 and intra-hour-range MAE from 28.460
to 18.651 EUR/MWh. QH scenario coverage remains low: S10 and S30 90% coverage
is 74.3% and 79.2%, respectively. These are descriptive held-out results, not
a calibrated-risk claim.

The four weeks were selected before optimisation by the frozen robust regime
ranking with at least 28 days separation:

- typical winter: 2--8 December 2024;
- high volatility: 4--10 November 2024;
- high prices: 13--19 January 2025;
- typical summer: 14--20 July 2025.

Every C1 interpretation is conditional on a maintenance-free normal-operation
week: neither the weekly eight-hour EAF maintenance nor the annual outage is
activated. The paths are counterfactual overlays, not observed 2024/25 QH
prices, and the weeks may not be annualised.

Phase-6D Gate A physically passes with zero validation failures. Its separate
120-hour C1 H-S10 performance tier reached the 900-second cap, so it is retained
as `performance_incomplete`, not misclassified as a physical capacity failure.
The governed 24-hour C1 gate remains proven infeasible before economics. The
authorized remedy is the explicit `24e48p` split horizon: exactly 24 hours of
D-only price/scenario information and execution inside a 48-hour physical
plan. Hours 25--48 have no price, bid, clearing, execution or settlement and
serve only as a physical continuation witness. No physical bound changed.

Gate run `20260731_split_horizon_24e48p_gate_v5` passes all six bounded C0/C1
hourly/QH price-insensitive and C1 hourly/QH-S10 trajectories, with 60/60 hard
checks, zero failures and exact bid-clearing reconstruction. Flat-price parity
means identical production and expected-objective parity within the frozen
0.1% MIP gap; aggregate carrier differences remain reported because the hour
and quarter-hour clearing constraints can select different equivalent timing.
The retained feasible bid incumbent removes an unnecessary canonical-bid
re-solve: H-S10 and QH-S10 planning require about 196 and 430 solver seconds in
the accepted gate, respectively, below the unchanged 900-second per-tier cap.
The v11 manifest consequently releases 80 D-only/S10/S30 rows and keeps only
the 32 true 48/72/96/120-hour price-horizon rows blocked for missing causal
Strict D+1--D+4 support. Stitched future D-only forecasts remain forbidden.

The short H2 mechanism run `20260731_h2_mechanism_s10_v3` completes all 18
week trajectories and 252/252 accepted solves. It uses only D-only/S10 and has
no horizon or scenario-count sweep. QH-flat causes material emergency import;
the shape overlay recovers EUR 463,571 in the observed week and EUR 109,310 in
the counterfactual winter bridge, but stochastic QH-shape still underperforms
hourly by EUR 121,305 and EUR 344,432, respectively. This adverse result is
retained and does not affect the frozen steel forecast-family choice.

The bounded steel run `20260731_c0_winter_abc_validation_v2` validates all
three central arms for the C0 winter case. All 21 daily plans terminate
optimally, seven-day production is identical at 129,452.055 t, and every
state-handoff and settlement reconstruction passes. Realised deltas are
`delta_QH-market = -EUR 34,006`, `delta_shape = +EUR 21,605` and
`delta_total = -EUR 12,401`; positive means saving. This single case is
executor evidence produced before the global blocker was identified; it is not
an authorized headline result or completion of the four-week C0/C1 matrix.
The follow-up `20260731_c0_objective_reconstruction_v1` passes all seven
scenario-wise expected-objective reconstructions; the maximum deviation from
the preserved lexicographic cost optimum is EUR 0.010001 and remains inside
the governed cost-preservation tolerance.

### Promoted representative planning selection (2026-08-01)

The representative runner now explicitly fixes
`planning_physical_tiebreak_mode: expected_cost_incumbent` (V1) for all A/B/C,
C0/C1, central S10 and steel-only sensitivity rows. It proves production
progress and expected represented cost, then retains the resulting feasible
incumbent without a third planning physical-tie solve. A cost-preservation
constraint remains active before any separate price-insensitive canonicalisation,
so V1 is not permission to accept a worse expected-cost optimum.

Frozen audit evidence records median planning runtime of 180.0 seconds versus
437.7 seconds for V0 (60.6% faster), about 191 versus 467 seconds for the full
day, identical expected cost, passing physical checks and three-process V1
reproducibility. The one-day realised-cost difference is EUR 1,288.83 (about
0.014%). Different inventories, flaring, commitments, bids and handoff are
accepted because those internal selections are not all priced; the small
observed economic magnitude is reported rather than treated as exact path
equivalence.
This project-level promotion supersedes the audit's earlier retain-V0
recommendation; the frozen audit files remain unchanged as historical evidence.

V0 `full_physical_tiebreak` remains selectable as an audit reference and the
general Phase-6D diagnostic default. Redispatch still executes production,
represented cost and `redispatch_physical_tiebreak`. All physical, material,
WAG, NG, steam, terminal and handoff gates and the 900-second cap remain in
force. Config, input lineage, solver diagnostics, experiment summaries and run
summaries record the planning mode, skipped planning tie solve, both planning
optima, solver version, seed 0, MIP gap 0.001 and integer tolerance `1e-9`.
A/B/C conclusions continue to use realised-cost differences; V0/V1 incumbent
selection is a stated limitation and exact V0 bid/path parity is not required.

### Pre-matrix behavioural gate result (2026-08-01)

Run `20260801_pre_matrix_behavioural_gate_v1` froze four eligible non-final
shadow days before solving: 2 March (typical/calm), 10 May (high volatility),
8 June (negative/low) and 9 September 2025 (high price). The seven required
Phase-0 evidence families were reused without new solves. The run declaration
covered nine synthetic trajectories and, only conditional on their success,
thirteen shadow trajectories. The four final weeks were excluded from
selection, tuning and solver execution.

The S0 C0 responsive trajectory passes all 37 physical checks. S0 C1 planning
proves zero production-progress deviation and the V1 expected-cost optimum of
EUR 9,689,932.602; expected-cost reconstruction is exact and maximum
bid-clearing reconstruction error is `3.1e-7` MWh. Under the frozen held-out
actual-price path, intervalwise clearing nevertheless creates a quantity path
that the unchanged physical redispatch model proves infeasible. One cleared
interval is outside the ten scenario-import envelopes, total cleared import is
7,720.177 MWh and the nearest complete planned scenario path is 49.812 MWh RMSE
away. This localises the hard failure to the mapping from out-of-sample
intervalwise bid acceptance to complete physical recourse, rather than to the
planning optimum, probability mass or bid reconstruction.

The decision is `BLOCK`. Seven remaining synthetic cases, all thirteen shadow
cases and all four final regime weeks remain unrun. Directional F18/F19 tests
and economic-rationality comparisons were therefore not reached. No emergency
import, imbalance optimisation, physical relaxation or retuning is authorized
as an implicit remedy. Also, the normal one-day `24e48p` run has no terminal
equality at physical hour 48; distance to the reference terminal band is only
a diagnostic under the shared non-terminal continuation policy.

The next gate is a separately approved methodological repair that guarantees
or explicitly models complete physical recourse after out-of-sample clearing
without leakage or changed physical bounds. After that repair, the full
synthetic and shadow gate must be rerun and pass. Only then may the frozen
four-week D-only/S10 central matrix and steel-only S30 sensitivity start. The
D--D+4 price-horizon sensitivity stays blocked until causal support exists;
mFRR, CVaR, ETS, export, product revenue, emergency import and imbalance remain
outside the active scope.

### Recourse repair and repeated behavioural gate (2026-08-01)

The historical S0 blocker above was diagnosed in
`20260801_s0_c1_recourse_diagnostics_v2`. The pre-fix clearing required zero
import at 08:00 UTC while the physical minimum was 5.275533 MWh. The actual
price exceeded the S10 price support and the retained, non-canonical incumbent
had placed a physically required block at a lower, sampled-only bid step.
Phase 6D now reconstructs the already feasible scenario imports analytically
using the previously frozen
`minimum_total_volume_then_highest_willingness_price` ordering. This adds no
solve, changes no scenario dispatch or expected-cost optimum and independently
reconstructs every scenario clearing. Post-fix run
`20260801_s0_c1_recourse_diagnostics_v3` proves exact clearing feasible and
reduces minimum recourse deviation from 5.275533 MWh to zero.

Repeated behavioural run
`20260801_pre_matrix_behavioural_gate_v2_canonical_bid` then completes all nine
synthetic trajectories: all are physically feasible, all solver tiers are
optimal and no performance-incomplete result occurs. The comparison contract
also excludes administrative `episode_id` from the physical-start hash and
revalues the unchanged flat-EUR-80 price-insensitive dispatch on common S10
prices without replanning. Responsive expected cost dominates that common
basis by EUR 122,801.70 in C0 and EUR 169,082.45 in C1; perfect foresight is
EUR 44,371.65 cheaper than forecast execution. These are gate diagnostics, not
final-week value claims.

The conditional shadow gate nevertheless stops after seven passing cases on
`shadow__typical_calm__2025-03-02__C__C1__responsive`. Exact actual-price
clearing is infeasible although zero of 96 quantities lie outside their S10
interval envelopes. Diagnostic run
`20260801_shadow_typical_calm_c1_path_splicing_v1` proves the nearest complete
scenario path feasible at 13.150270 MWh RMSE, but exact and envelope-clipped
paths infeasible. Minimum physical recourse is 4.787437 MWh in one quarter at
17:00 UTC; the exact IIS has 41 members spanning clearing, route capacities,
DRP/EAF paths and VN25. This is
`structural_path_splicing_inside_quantity_envelope`, not a bid-step, unit,
timing or physical-bound defect.

The active decision remains `BLOCK` before the four final weeks. Robust/path-
feasible bid coupling would preserve exact physical execution but materially
expand the stochastic MILP; explicit imbalance or bounded recourse would
change settlement and market semantics; S30 may improve support but cannot
guarantee path feasibility and already has adverse runtime evidence. None is
promoted implicitly. A user-authorized method decision and a repeated complete
shadow PASS are required before the central four-week matrix. D--D+4, mFRR,
CVaR, ETS, export, product revenue and emergency import remain outside scope.

### Penalised execution recourse selected (2026-08-01)

The user selected explicit execution recourse for the remaining out-of-sample
path-splicing risk. For every executed market interval, physical net import may
differ from the DA-cleared E-program through separate non-negative upward- and
downward-consumption deviation variables. Their absolute MWh sum enters the
redispatch represented-cost tier at EUR 5,000/MWh. The DA pay-as-cleared
settlement remains based only on cleared volume; the artificial recourse
penalty is reconstructed and reported separately. A trajectory is described
as E-program compliant only when its absolute deviation is zero.

This is a deliberate market-semantics change, not a physical-bound relaxation
or a claim about observed imbalance prices. Emergency import remains disabled.
The governed contract has one fixed penalty only: EUR 5,000/MWh. No imbalance-
penalty sensitivity is retained. The full synthetic and shadow gate
must pass under this contract before any final regime week is solved. Positive
recourse remains a reported limitation and economic cost, not a hidden
feasibility adjustment.

### Penalised-recourse behavioural gate PASS (2026-08-01)

Run `20260801_pre_matrix_behavioural_gate_v3_penalised_recourse` completes all
22 trajectories and returns `PASS`: 9/9 synthetic and 13/13 shadow cases pass,
with no infeasibility, hard physical/economic failure, solver time limit or
final-week use. The former typical/calm C1 path-splicing blocker is feasible
under the authorised recourse interface.

Three cases use material recourse at EUR 5,000/MWh: the synthetic negative-
price C1 stresscase uses 0.608812 MWh (EUR 3,044.06), the shadow negative/low-
price C1 case uses 0.060734 MWh (EUR 303.67), and the former typical/calm C1
blocker uses 10.683906 MWh (EUR 53,419.53). All other cases are zero within the
governed numerical tolerance. These three trajectories are not E-program
compliant. The 10.683906 MWh result exceeds the earlier lexicographic diagnostic
minimum of 4.787437 MWh, proving that the finite penalty can trade recourse
against represented cost. Therefore central EUR 5,000/MWh runs are authorized,
but economic interpretation is unavailable for any positive-imbalance case.
No final representative week has yet
been solved at this gate.

### Central matrix controlled stop (2026-08-01)

The first central campaign,
`20260801_four_week_central_s10_penalised_recourse_v1`, was controlled-stopped
and is not thesis-result usable. Fourteen of 56 selected experiments have
complete seven-day summaries, one high-prices B-QH-flat C1 experiment has only
two completed days, and no complete four-week matrix exists. The high-prices
C1 A-hourly result uses 248.503443 MWh recourse (EUR 1,242,517.21 penalty) and
the C-QH-shape result uses 283.258327 MWh (EUR 1,416,291.63). The corresponding
B-QH-flat C1 week is incomplete after its third rolling day failed to produce a
checkpoint during more than 75 minutes of observation. C0 A/B/C trajectories
completed so far remain zero-recourse.

This proves that the one-day behavioural PASS did not guarantee acceptable
multi-day rolling C1 recourse or runtime. The high-prices C1 A/B/C comparison
is unavailable and the completed C1 cost values are dominated by the artificial
penalty. The remaining regime experiments must not be resumed until rolling
state-dependent minimum imbalance is diagnosed and eliminated or a different
method is explicitly authorized, and per-tier runtime/progress reporting gives a
bounded restart decision. No market-value conclusion may use this incomplete
campaign.

### Conditional minimum-imbalance gate and hard stop (2026-08-01)

The lingering Python process for
`20260801_four_week_central_s10_penalised_recourse_v1` was verified by PID,
Python executable, exact runner command, 20:24:18 start time and active CPU
before termination at 23:25:16 local time. PID 28756 disappeared, the runroot
stopped changing and no other Python/Gurobi C6 run remained. The preserved
runroot now contains `termination_addendum.json` with
`thesis_result_usable=false`, `resume_authorized=false` and
`superseded_by_conditional_minimum_imbalance_gate=true`.

Redispatch now uses the fixed hierarchy production progress, represented
operational cost plus exactly EUR 5,000 times absolute imbalance, then the
physical tie-break. A separate minimum-absolute-imbalance solve is conditional:
it is skipped when the economic solution is already zero. When economics uses
positive imbalance, one diagnostic solve minimizes only `d_plus + d_minus`
under the same state, physics, cleared E-program and preserved production
optimum. A zero minimum hard-fixes both deviation variables to zero and reruns
economics; a positive minimum is `emergency_recourse`, has no A/B/C result and
stops the complete invocation. Solver exceptions and unproven optimality fail
closed. Atomic run control and start/finish records now expose every solver
tier and prevent resume whenever `resume_authorized=false`.

Run `20260801_conditional_minimum_imbalance_gate_targeted_v1` first passes
`S0_C1_responsive` with exactly 0 MWh, no minimum solve and no penalty. Its
clearing, DA settlement, penalty, state handoff and Phase-6D physical identities
all pass. The subsequent 2-March-2025 typical/calm C1 case first chooses
10.683906 MWh downward-consumption imbalance in the EUR-5,000 economic tier.
The conditional solve proves an optimal positive minimum of 4.787437 MWh over
two intervals, maximum 2.562389 MWh, costing EUR 23,937.18 at the fixed penalty.
It is therefore classified `emergency_recourse`; A/B/C eligibility and rolling
continuation are false. In accordance with the early-stop contract, the
15-January high-price day and the one-week trial were not started.

Decision: `blocked_before_four_week_run`. This is a physical/path-feasibility
blocker, not a penalty-calibration question. No penalty sensitivity, remaining
week, S30, horizon, H2, mFRR or CVaR run is authorized. A new methodological
decision is required before any further economic matrix execution.

### Validation-derived path-feasibility repair and runtime stop (2026-08-02)

The bounded repair keeps the ten economic Strict S10 price paths, scenario ids,
probabilities and expected-cost expression unchanged. A validation pattern is
a probability-free mask of accepted canonical bid-step ranks by lead position;
it contains no transported raw price. Each feasibility block clones the same
initial state, quarter-hour physics, production and terminal contract and links
its physical net import directly to the shared `bid_volume_mwh` variables under
that mask. Its cost contribution is exactly zero. At most one worst violating
pattern may be added per round and the governed maximum is three rounds.

Run `20260802_path_feasibility_blocker_phase_b_v1` reproduces the 2-March C1
minimum at 4.787436618 MWh after the EUR-5,000 economic solution uses
10.683905530 MWh. One QH validation pattern adds 9,038 variables, 204 binaries
and 9,570 constraints. The repaired S10 planning model remains optimal, the
actual clearing redispatch is optimal at exactly 0 MWh and the conditional
minimum-imbalance solve is not started. The repaired planning tiers take
10.761 s for production progress, 140.965 s for expected cost and 525.914 s for
the feasibility-aware canonical bid tie-break; every tier remains below 900 s.

The complete behavioural invocation
`20260802_path_feasibility_behavioural_phase_c_v2` then completes only
`S0_C0_responsive`. The following normal, still unaugmented
`S0_C1_responsive` expected-cost tier has 91,916 variables, 2,040 binaries and
95,681 constraints and terminates `aborted/maxTimeLimit` after 906.454 s. No
validation path is added, no later synthetic or shadow case is started and the
run control is non-resumable. The earlier `v1` Phase-C attempt has zero solver
events, is non-resumable and is retained only as pre-solve diagnostic evidence
of an exact duplicate-pattern manifest that was subsequently deduplicated.

Decision: `blocked_before_final_weeks`. The one-day structural blocker is
repaired, but the mandatory 9/9 synthetic plus 13/13 shadow gate is incomplete
because ordinary S10 planning cannot prove optimality within the frozen cap.
No final day, final week, four-week matrix, S30, horizon, penalty, H2, mFRR or
CVaR run is authorized.

### Reduced path-feasibility canonicalisation and runtime repair (2026-08-02)

The full feasibility-aware canonical bid MILP is superseded for the bounded C6
repair. The accepted sequence is still production progress followed by the
unchanged S10 expected-cost objective. Bid steps with identical acceptance
signatures over the ten economic paths and every active feasibility pattern are
reduced exactly: only the highest willingness-price step for each non-empty
signature remains free. When an augmentation is active, all 2,040 economic
scenario binaries are fixed at the proven expected-cost incumbent and only the
feasibility-block binaries remain free for reduced canonicalisation. Unused bid
steps are set analytically to zero and both economic and feasibility clearing
are reconstructed before acceptance. This secondary selection adds no
probability or cost term and does not alter the bid/clearing equations.

The raw expected-cost incumbent without reduced canonicalisation is rejected:
although its separate minimum-imbalance solve can find zero, its economic
redispatch initially uses avoidable imbalance. The full old canonical tier took
416--526 seconds in the recorded comparison. The accepted reduced tier takes
34.055--37.396 seconds across three fresh processes; complete augmented
planning takes 152.283--163.684 seconds. Each process reproduces exact zero
imbalance without invoking the conditional minimum solve, identical expected
cost EUR 9,139,260.165057492, identical realised cost EUR
8,223,815.621356655, and identical bid, scenario-dispatch, clearing, physical-
dispatch and next-state hashes. The one added path leaves 202 feasibility
binaries unfixed after the 2,040 economic binaries are fixed.

Targeted performance evidence rejects a cold start, native two-objective solve,
signature reduction alone and `MIPFocus=3` as runtime improvements. The only
promoted performance option is deterministic `MIPFocus=1`; seed 0, MIP gap
0.001, `IntFeasTol=1e-9` and the 900-second cap remain frozen. On the former
`S0_C1_responsive` blocker it reduces the expected-cost tier from 779.704
seconds warm (843.242 cold) to 249.603 seconds, with a 0.0996% proven gap, one
node and 193.89 work units. Total production-plus-cost time is 255.535 seconds.

The 9+13 runner now writes deterministic plant `eligibility_record`s before
the first solve. Eligibility uses only the frozen case, policy, grid and ex-ante
point support; final periods, actual prices and solved dispatch are forbidden.
Route substitution is pre-classified `not_applicable` because the one-day route
quota contract does not prove substitution headroom. Applicable EAF/DRP and
VN25/boiler/flare mechanisms receive hard directional checks, while IJ01 named
NG, route/output invariance, physical identities and at least one material named
C1 response remain fail-closed. Economic-rationality and plant checks now enter
the same 9+13 gate decision. Static validation passes 129 C6 tests and Ruff.
The broad gate has deliberately not been started in this engineering period.

Decision: `blocked_before_final_weeks_pending_full_behavioural_plant_gate`.
The next allowed solve is one new minimal diagnostic-validation invocation of
the 9 synthetic plus 13 non-final shadow cases. No final day, rolling week,
four-week matrix or excluded sensitivity is authorized before that invocation
passes without imbalance, emergency recourse, time limit, physical error,
economic hard failure or applicable plant failure.

### Restricted parent bridge passes; frozen shadow-pattern coverage does not (2026-08-02)

The promoted runtime bridge is auxiliary only. On every augmented round it
seeds the shared bid variables and economic scenario state from the preceding
proven plan, fixes only the 2,040 economic-scenario binaries, and solves one
restricted expected-cost problem. It then removes that objective, unfixes all
economic binaries and solves the complete, unchanged S10 expected-cost MILP.
No bridge result is eligible as a final plan and no preservation constraint is
added. Run `20260802_s0c1_bridge_v2` proves the exact two-path child optimal in
372.184 seconds after an 11.861-second bridge; the reduced canonical tier takes
73.740 seconds. S10 probability mass remains 1, its contract hash is unchanged,
and the two feasibility paths add no probability or expected-cost term.

Targeted end-to-end run
`20260802_s0c1_constraint_generation_bridge_v2` is fail-closed after one
trajectory. Baseline expected cost is optimal in 265.058 seconds. Round 0 finds
minimum imbalances of 114.148205, 88.725558, 42.893936 and 122.881657 MWh for
the four permitted QH shadow masks and adds only the worst negative/low-price
mask. The parent bridge and full expected-cost re-solve both complete in round
1. The reduced canonical tier reports optimality after 903.536 seconds and
therefore also misses the strict below-900-second runtime criterion. All four
shadow-mask separation solves then prove zero imbalance.

The actual controlled S0 clearing nevertheless enters emergency recourse. Its
economic solution uses 29.093767 MWh imbalance and the separate minimum solve
proves 27.646412 MWh upward-consumption imbalance at interval 79. The penalty
is reconstructed exactly once at EUR 5,000/MWh, `abc_comparison_eligible=false`
and `resume_authorized=false`; no later case or final period is run. A rank-only
diagnosis shows that the S0 actual mask equals none of the four frozen QH
shadow masks, differs at 91--96 of 96 lead positions, and lies outside their
leadwise rank envelope at 72 positions. At affected interval 62 its first
accepted rank is 12 versus shadow ranks 1, 4, 7 and 1.

Decision: `blocked_before_final_weeks_requires_pattern_source_decision`. Adding
another path from the existing four cannot repair this uncovered clearing
combination because all four already pass separation. Continuing requires an
explicit choice between admitting additional pre-final validation-derived
patterns (for example controlled synthetic validation masks) or authorising a
stronger robust pattern contract. Neither change is inferred silently. The
9+13 gate, rolling week and every final-week run remain unauthorized.

### Fixed economic epsilon-optimality policy (2026-08-02)

The C6 sequential solver now uses `MIPGap=0.002` only while minimising an
economic cost objective. The physical `mip_gap_limit=0.001` remains separate;
production progress, feasibility-path separation, minimum imbalance and all
physical tie-breaks still require normal optimal termination. The fixed EUR
5,000/MWh penalty and the zero-imbalance fail-closed gate are unchanged.

Economic acceptance requires a finite incumbent and best bound, a loaded
objective matching that incumbent, and a reconstructed relative gap no larger
than 0.002. A time-limit may be labelled `epsilon_optimal` only under that
certificate and only if all later objective, clearing, settlement, physical
and zero-imbalance reconstructions pass. Reports retain incumbent/UB, bound/LB,
absolute band and relative gap. Later A/B/C expected-objective differences use
`[LB_A - UB_B, UB_A - LB_B]`; realised-cost point differences remain separately
reported and are never disguised as solver-certified intervals.

Run `20260802_s0c1_p3_focus2_v1` numerically meets the new rule with UB EUR
9,694,749.389854, LB EUR 9,684,082.199056, a EUR-10,667.190798 band and
0.001100306 relative gap. It cannot be promoted because it contains no complete
bid, economic-scenario, feasibility-path, clearing, redispatch or handoff
solution artifact. The recorded reuse decision is therefore
`gap_pass_but_reconstruction_unavailable`; validation resumes only at the
smallest unfinished path-count-1 S0--C1 gate. No completed C0, synthetic or
shadow gate and no final period is rerun for this policy change.

Minimal rerun `20260802_s0c1_path1_epsilon002_v1` passes. Production progress
is strictly optimal in 17.074 s. Expected cost takes 490.014 s and is certified
with UB EUR 9,693,536.508257, LB EUR 9,683,839.208503, band EUR 9,697.299754
and relative gap 0.001000388. Expected-cost reconstruction error is zero;
maximum bid and feasibility-path reconstruction errors are 3.32e-8 MWh and
5.68e-14 MWh. The feasibility path remains probability-free and S10 mass is
unchanged at one within floating-point tolerance. The next gate is only the
unfinished S0--C1 three-round constraint-generation/actual-zero-imbalance
trajectory; final periods remain blocked.

Targeted continuation
`20260802_s0c1_constraint_generation_epsilon002_v1` closes the S0--C1
zero-imbalance blocker. Round 0 adds the negative/low shadow mask after a
122.881657-MWh maximum violation. Round 1 adds the typical/calm shadow mask
after a remaining 9.204178-MWh violation. Round 2 proves all five compatible
validation masks at zero. Final actual redispatch directly reaches 0 MWh,
does not call the minimum-imbalance tier and passes 48/48 physical and
reconstruction checks.

Round planning runtimes are 199.625, 183.473 and 173.162 s. The final model
contains 109,992 variables, 2,448 binaries and 114,819 constraints. Its
expected-cost interval is [EUR 9,676,898.062312, EUR 9,696,280.717435], with
EUR 19,382.655123 width and 0.001998978 gap. Redispatch's economic interval is
[EUR 8,484,703.202998, EUR 8,501,552.185900], gap 0.001981871; physical tiers
remain strict. A reporting-only KeyError after artifact persistence was fixed
and the PASS summary reconstructed from the unchanged result, solver and
48/48 check artifacts without another solve.

The plant gate resumes case-by-case rather than restarting completed work.
Every continuation freezes eligibility before solving, rejects final-test
cases and defers cross-case plant/economic judgement to a later aggregation.
`S1_C0_responsive` passes with 0 MWh and 40/40 checks.
`S1_C0_price_insensitive` passes with 1.995e-6 MWh, within the fixed 1e-5-MWh
zero tolerance, and 40/40 checks. S0 C0/C1 were not rerun and no final period
was read.

### Resumed synthetic behavioural and plant gate PASS (2026-08-02)

The fixed-gap continuation completes only the unfinished synthetic manifest
cases. `S1_C1_responsive`, `S1_C1_price_insensitive`, `S2_C1_responsive`,
`S3_C1_responsive` and `S4_C1_true_pf` each pass at 0 MWh with 48/48 physical
and reconstruction checks. The S3 economic epsilon incumbent initially used
avoidable imbalance; the strict minimum tier proved zero, the hard-zero
economic re-optimisation met the 0.2% certificate, and the final physical tier
again returned zero. The initial positive-imbalance incumbent is not an
accepted result. Completed S0 and C0 cases were not solved again.

Solve-free aggregation initially exposed two reporting-contract defects. An
eligibility-only source root was incorrectly ignored when it did not also
contribute a case result. In addition, constraint-generated cases used an
outcome-derived terminal-inventory hash and omitted the frozen physical
feasible-set hash, falsely making identical physical contracts look unequal.
Eligibility is now aggregated independently of result ownership, and one
shared helper derives terminal and feasible-set identities exclusively from
the frozen pre-solve context. No physics, scenario, bid, penalty, forecast or
maintenance input changed.

Run `20260802_synthetic_plant_aggregate_epsilon002_v3` aggregates the nine
previously solved cases with zero models and zero solves. It returns `PASS`:
9/9 cases, zero hard economic/plant failures, zero physical failures and
maximum imbalance 1.994853e-6 MWh. The responsive/price-insensitive and true-PF
comparisons share the reconstructed frozen feasible-set contract and have the
expected cost direction. Static validation passes 108 targeted C6 tests,
Ruff, the portable-path/secret check and `git diff --check`.

Decision: `blocked_before_final_weeks_pending_13_case_shadow_gate`. The next
unfinished work is the thirteen-case non-final shadow/regime behavioural and
plant gate under the same zero-imbalance/path-feasibility method. The completed
2-March blocker/path gate is not repeated. No final day, rolling week, final
week, four-week matrix or sensitivity is authorized yet.

### Non-final shadow/regime and plant gate PASS (2026-08-02)

The thirteen-case shadow continuation passes under the fixed 0.2% economic-gap
and strict zero-imbalance contracts. All cases were solved in separate governed
non-final roots and then combined without a solver call in
`20260802_shadow_plant_aggregate_epsilon002_v2`. The aggregation audit accepts
13/13 artifacts, reports zero hard economic/plant failures, zero physical or
financial failures and maximum absolute imbalance `2.2708565759e-6 MWh`.
Together with the earlier synthetic aggregate, the complete behavioural
population is 9/9 synthetic plus 13/13 shadow PASS.

Old shadow outputs could not be promoted under the fixed epsilon policy because
they did not retain numeric incumbent/bound certificates and the complete
current reconstruction contract. They remain diagnostic evidence; no
current-code completed trajectory was repeated. Current C1 planning runtimes
were approximately 159 s (high price), 547 s (high-volatility shape), 400 s
(negative/low), 413 s (typical/calm), 44 s (price-insensitive), 24 s (true-PF),
102 s (hourly) and 762 s (QH-flat). No solve crossed the 900-s cap, no emergency
recourse occurred and no final-period input was used.

The first solve-free aggregate attempt treated the one-scenario
price-insensitive benchmark as if it were a responsive S10 plan and blocked.
The audit now distinguishes responsive plans (exactly ten economic scenarios)
from the intentionally single-path price-insensitive and true-PF benchmarks;
all retain probability mass one. The failed aggregate remains non-resumable
and is superseded by the v2 PASS root.

The next and only open pre-freeze execution gate is one frozen non-final
maintenance-free rolling week, 16--22 June 2025. It is the earliest complete
Monday--Sunday week with complete Strict point/S10/overlay support after three
already frozen shadow sources. Feasibility masks are allowed only when their
source day precedes 16 June; the contemporaneous week never supplies its own
mask and the later high-price shadow source is excluded. The frozen matrix is
six experiments (C0/C1 by hourly, QH-flat and QH-shape), 42 daily trajectories,
24-hour planning/execution and seven independent rolling state chains.

The runner reuses the same bounded one-pattern-per-round constraint generator,
passes the current rolling state into both planning and validation-path
separation, flushes a compact checkpoint after every day and reports weekly
expected-cost LB/UB sums plus certified A/B intervals
`[LB_A-UB_B, UB_A-LB_B]`. Static validation passes 111 relevant C6 tests, Ruff
and the solve-free C6 preflight. No rolling-week solve has started. Decision:
`blocked_before_final_weeks_pending_non_final_rolling_week`; no final day,
final week, four-week matrix or sensitivity is authorized meanwhile.

Runtime preflight uses the matched current C1 shadow tiers: hourly completes six
tiers in 69.2 s, QH-flat twenty tiers in 715.1 s and QH-shape fifteen tiers in
492.9 s. Repeating that incidence for seven stateful days projects about 2.48 h
of C1 solver time; C0, model construction, artifact writes and possible changed
rolling-state separation lift the prudent week estimate to 3.0--3.5 h. The
runner therefore expects roughly 390 tier solves (minimum 210) and 180--220
model instances, checkpoints every completed day and must be started only in a
fresh four-hour compute period. Four comparable central weeks project at least
12--14 h before any separately authorized benchmarks; they remain a later
checkpointed compute block, not part of the rolling-gate invocation.

### Non-final rolling-week PASS and final method freeze (2026-08-02)

Run `20260802_non_final_rolling_week_epsilon002_v1` completes the previously
open rolling gate. All 42/42 daily trajectories and 6/6 C0/C1 A/B/C
experiments pass. The run records 1,848/1,848 physical and financial checks,
11/11 hard plant checks, zero emergency recourse and zero conditional
minimum-imbalance solves. Maximum daily absolute imbalance is
`2.0000716411e-6 MWh`, within the fixed numerical zero tolerance, and maximum
weekly production spread across arms is `2.0000152290e-6 t`. Every rolling
state reaches 168 executed hours.

The governed run finished in about 55.2 wall-clock minutes. Its 279 completed
solver tiers total 2,975.0 s, with median 0.782 s, p95 81.012 s and maximum
279.103 s. No tier reached the 900-s cap. The 21 C1 daily planning plus
separation sequences have median 116.983 s, p95 287.548 s and maximum
341.257 s. Two QH-flat days required embedded validation paths (one and two
patterns respectively); every other accepted day required none. Economic S10
mass remains one, feasibility paths retain no probability or expected-cost
weight, and all expected-cost, bid, path, settlement and physical
reconstructions pass.

The validation-week economics are mechanism evidence only. C0 realised
differences are EUR +40,570.25 for A minus B, +182.30 for B minus C and
+40,752.55 for A minus C. C1 differences are EUR -43,782.22, +35,761.56 and
-8,020.66 respectively. The broad C1 expected-objective difference intervals
cross zero where the 0.2% certificates overlap; no positive effect is treated
as a gate condition or generalized to the final regimes.

The representative executor now calls the same bounded constraint-generation
planner for every final C1 responsive S10 day. It passes the current rolling
state and shared bid variables directly, assesses only the pinned non-final
hourly/QH acceptance-mask pool, adds at most one worst path per round and fails
closed after at most three rounds. It independently hashes the ten economic
scenario prices and probabilities before accepting the augmented plan. The
patterns remain settlement-ineligible, forecast-metric-ineligible and
probability-free; final prices are not pattern sources and raw validation
prices are not transported. C0, price-insensitive and true-PF benchmark
semantics remain unchanged, while the existing zero-imbalance redispatch gate
still applies to every trajectory.

The executable method is frozen in
`steel_c6_final_method_freeze_v1.yaml`. The method identity, excluding the
separate runtime-authorization block, is
`e34bdf490ffe800795b00423316e8c3c1618deb57006df0fba36513584c5d376`.
It pins the Phase-6D engine, behavioural path planner, representative executor,
three configs, validation evidence, feasibility-pattern manifest and selected
week/experiment manifests. The representative config still has
`full_four_week_matrix_authorized=false`; changing authorization may not alter
the frozen method payload.

Final compute preflight contains 24 central stochastic experiments plus 32
shared-grid price-insensitive/true-PF benchmarks: 56 experiments and 392 daily
rolling trajectories. From the measured six-experiment week, a cautious total
projection is 10--14 wall-clock hours, with `output_policy=minimal`, a fresh
ignored thesis-candidate runroot, checkpointing after every day and an
immediate fail-closed stop on emergency recourse or an unaccepted solver tier.
No final day or week has been solved. Decision:
`path_feasibility_gate_pass_ready_for_final_week_authorisation`; the next step
requires explicit authorization for the long final compute block.

A final solve-free authorization audit found that the previous runner rejected
every true full-matrix flag unconditionally. This was an execution-boundary
defect: user permission could not have opened the frozen matrix without another
code edit. The boundary now has two explicit states. The default false state
retains no receipt and continues to reject `--all-central-ready`. The true
state requires a non-empty receipt, timezone-aware timestamp and exactly the
frozen 56-row set: four weeks, 24 central S10 rows, 32 benchmark rows, C0/C1,
the four governed arm/grid labels, 24-hour horizon and inactive maintenance and
outage flags. Partial, sensitivity-mixed or altered selections fail closed.
The authorization block remains outside the frozen method-identity hash. Static
tests prove both refusal and exact-set acceptance without reading prices or
starting a solver; authorization remains false.
