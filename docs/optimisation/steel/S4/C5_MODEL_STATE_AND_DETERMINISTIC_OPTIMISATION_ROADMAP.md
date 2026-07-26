# C5 Model State and Deterministic Optimisation Roadmap

## Decision in one sentence

Current gate: `phase1_full_site_boundary_and_anchor_hierarchy_frozen_phase2_go`. The repaired bounded DEVELOPMENT allocation-envelope run `steel_c5_wag_ng_allocation_envelope_v6_20260726` passes 4/4 hook-absent normals, 8/8 trajectories and 56/56 endpoint windows with all cost, state, physical, bound and evidence guardrails. The 2.528-TWh/y real WAG-only anchor is above the certified represented-cost-optimal maximum in all four frozen cases. This is a boundary/result finding, not calibration or candidate promotion. The accepted Phase-1 overlay now governs the full-site boundary and anchor hierarchy; strict source-ranked contracts, WAG yields, physical parameters and held-out results remain unchanged. Phase 2 may proceed only within this frozen hierarchy. Bidding, settlement, revenue, ETS, stochasticity, CVaR and mFRR remain unauthorised.

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
For the active rolling price-response path it solves lexicographically:
minimum cumulative production-progress deviation first, represented procurement
cost second, then the governed physical tie-breaker within the preserved
optima. This supersedes the cost-first ordering after that ordering accumulated
343-528 t of C1 production credit and broke recursive rolling feasibility.
Residual electricity/NG, BFG/COG/BOFG, steam,
internal generation, inventory, revenue and ETS remain unpriced. BF pellets
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
price-response analysis. DAM bidding, settlement, export revenue,
stochasticity and live-market operation remain inactive, and active BF routes
still lack a BF-pellet burden.

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
| HSM/PEFA | partial throughput-linked development controllers exist | activate only source-traceable routes; no invented mix |
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
held-out evaluation.

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

#### Phase-1 accepted boundary freeze

The accepted overlay has explicit precedence over older user-authorized
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

This reopening does not authorize an exact digital-twin claim or combine the
physical fuel/oxidation CO2 ledger with the first-order full-site ledger. The
Tata questionnaire remains outside this calibration workstream.

## 7. Explicit no-go items

The physical, fixed-reference S2, governed point-forecast integration and
deterministic response diagnostics pass. The accepted physical baseline remains
separately price-free; the governed deterministic-response interpretation is
complete and its next use is bounded thesis-manuscript integration, not live
market operation or bidding. Do not add:

- a static C0 hour calendar or fixed production profile;
- fixed C0/C1 route shares chosen to make the model feasible;
- residual electricity, NG, coke, slab or WAG as hidden supply;
- aggregate/mixed WAG physical allocation, a fixed WAG/NG ratio or Wobbe;
- aggregate process CO2 plus Mode-B fuel CO2 in one total;
- ungoverned prices, live-market operation, DA bidding or settlement, generator
  export revenue, ETS, mFRR, stochasticity, CVaR or product revenue;
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
