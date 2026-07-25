# C5 Current Model Assumptions For Review

Purpose: compact supervisor/client review pack for the current C5 Tata Steel IJmuiden-inspired public-source development model. This is not a confidential Tata digital twin and not an approved economics model.

## A. One-Page Executive Summary

The current C5 model is a physical/accounting baseline for two configurations:

- `C0`: current BF-BOF reference route.
- `C1`: Phase 1 hybrid route with retained BF-BOF capacity plus NG-DRP and EAF.

The active comparison target is `6.75 Mt/y` liquid steel for both C0 and C1. Public raw anchors remain validation context: C0 around `7.2 Mt/y` liquid steel and C1 around `6.8 Mt/y` liquid steel.

Already represented in the C5 stack:

- BF-BOF and C1 DRP/EAF route material accounting.
- PEFA/pelletizing and pellet burden accounting.
- Bounded coke reconciliation.
- DRI buffer handoff between DRP and EAF.
- DSP downstream accounting and HSM/WBW scaffold from C5l_d.
- Linde/ASU oxygen accounting.
- Boiler/steam mass-flow circuit.
- IJ01/VN25 generator interface.
- Buffer/store register and annual C0/C1 reconciliation.
- Residual electricity/NG and CO2 boundary diagnostics.

Explicitly not ready and not allowed in the current C5 baseline:

- Economics, product revenue objective, DA revenue, generator export revenue, mFRR, stochasticity, CVaR.
- Full CO2 objective, ETS-ready CO2 total, Scope 2 CO2, residual electricity/NG loads.
- Final denominator freeze.
- Treating validation anchors as executable constraints.

Main review need before economics: confirm the active production basis, denominator policy, route split, DRP/EAF material coupling, DRP oxygen basis, generator/WAG caveats, residual energy boundary policy, and first CO2 boundary.

## B. Configuration And Production Assumptions

| Item | Current assumption | Status | Review point |
|---|---:|---|---|
| C0 configuration | Current BF-BOF reference | modelling_policy | Accept as reference baseline |
| C1 configuration | Phase 1 hybrid BF-BOF + NG-DRP + EAF | modelling_policy | Accept as C1 base case |
| C1 plant convention | BF7 inactive, KGF2 inactive, BF6 and KGF1 retained | modelling_policy | Confirm retained/inactive assets |
| Active production target | 6.75 Mt/y liquid steel | development_reconciliation | Confirm as active comparison basis |
| Raw liquid steel anchors | C0 7.2 Mt/y, C1 6.8 Mt/y | source_backed_validation_anchor | Keep context-only or enforce later |
| C1 BOF route output | 3.4 Mt/y liquid steel | development_reconciliation | Confirm route split |
| C1 EAF route output | 3.35 Mt/y liquid steel | development_reconciliation | Confirm route split |
| Final-product proxy | C0 6.2591 Mt/y, C1 6.8005 Mt/y | development_reconciliation | Do not freeze denominator yet |
| Raw final-product anchors | C0 6.9 Mt/y, C1 7.0 Mt/y | source_backed_validation_anchor | Context only |

Interpretation: the raw public anchors are used to check plausibility, not to force the model. The current C5 development comparison is the active `6.75 Mt/y` basis.

Likely denominator recommendation for later: dual reporting. Use active liquid-steel target as the primary physical/economic denominator and report final-product proxy as a diagnostic until imported slab and downstream route-origin conventions are resolved.

## C. Major Material-Route Assumptions

| Item | C0 | C1 | Unit | Status |
|---|---:|---:|---|---|
| PEFA fired pellets | 4.3125 | 4.963235 | Mt/y | development_reconciliation |
| Imported pellets | 1.40625 | 0.198529 | Mt/y | development_reconciliation |
| BF pellet demand | 5.71875 | 1.405803 | Mt/y | development_reconciliation |
| DRP pellet demand | 0 | 3.755962 | Mt/y | development_reconciliation |
| DRP DRI output | 0 | 2.7794116 | Mt/y | development_reconciliation |
| EAF DRI input | 0 | 2.7794116 | Mt/y | development_reconciliation |
| EAF liquid steel | 0 | 3.35 | Mt/y | development_reconciliation |
| EAF scrap input | 0 | 1.01505 | Mt/y | development_reconciliation |
| EAF active DRI coefficient | 0 | 0.829675 | t DRI/t LS | sensitivity_required |
| EAF source-review DRI coefficient | n/a | 0.848 | t DRI/t LS | development_candidate |

Key caveats:

- The active EAF DRI coefficient is a route reconciliation value, not an independent Tata EAF recipe.
- The source-card/review value `0.848 t DRI/t LS` should be enforced only by decision or tested as a sensitivity.
- Bounded coke reconciliation is active as the C5m_f development baseline. External/unmodelled coke is fallback-only and must not become hidden slack.
- Bulk solid stores are present for accounting/continuity but practically non-binding; they are not free sources.

## D. Downstream And Product Assumptions

| Item | Current value/policy | Status | Caveat |
|---|---:|---|---|
| DSP output | 1.35 Mt/y in C0 and C1 | development_reconciliation | Raw 1.5 Mt/y anchor not enforced |
| DSP liquid-steel input | About 1.4175 Mt/y | development_reconciliation | Check again during denominator review |
| DSP internal scrap/loss | Reporting-only | development_reconciliation | Not an economics denominator |
| HSM/WBW scaffold | C5l_d `base_0_50` preserved | development_reconciliation | Not overwritten by C5p_d |
| C1 imported slab anchor | 0.6 Mt/y context | source_backed_validation_anchor | Not modelled as a store |
| DSP route-origin tracking | Incomplete | missing_anchor | Needs later repair if route-specific denominator is used |

Current recommendation: do not freeze the denominator. Use active liquid steel as primary for first economics design and final-product proxy as a secondary diagnostic until route-origin and imported slab accounting are resolved.

## E. Energy And Utility Assumptions

### Electricity

| Component | C0 | C1 | Unit | Status |
|---|---:|---:|---|---|
| PEFA electricity | 0.091856 | 0.105717 | TWh_e/y | development_reconciliation |
| DRP electricity | 0 | 0.231525 | TWh_e/y | development_reconciliation |
| EAF electricity | 0 | 1.413700 | TWh_e/y | development_reconciliation |
| DSP electricity | 0.075600 | 0.075600 | TWh_e/y | development_reconciliation |
| ASU electricity | 0.357375 | 0.392857 | TWh_e/y | source_backed_current |
| Steam-circuit internal electricity | 0.032360 | 0.015035 | TWh_e/y | development_reconciliation |
| IJ01/VN25 generator offset | 2.067665 | 0.935277 | TWh_e/y | development_reconciliation |
| Gross modelled process demand | 1.742724 | 3.033750 | TWh_e/y | development_reconciliation |
| Exposure after offsets | 0 floor | 2.098472 | TWh_e/y | development_reconciliation |

C0 over-offset issue: current modelled process demand is lower than internal electricity offsets. This is a boundary warning, not a full-site net export or net import claim. Residual electricity is incomplete.

### Natural Gas

| Component | C0 | C1 | Unit | Status |
|---|---:|---:|---|---|
| DRP NG | 0 | 27.516175 | PJ_LHV/y | development_reconciliation |
| EAF NG | 0 | 0.1675 | PJ_LHV/y | development_reconciliation |
| VN25/IJ01 generator NG | 0 | 4.1 | PJ_LHV/y | development_reconciliation |
| Boiler/steam NG backup | 0 | 0 | PJ_LHV/y | development_reconciliation |
| PEFA NG backup | 0 | 0 | PJ_LHV/y | development_reconciliation |
| Total modelled NG | 0 | 31.783675 | PJ_LHV/y | development_reconciliation |

Residual/background NG is not modelled. HSM/WBW, sinter, boiler and site residual NG anchors remain incomplete or weak.

### WAG And Generators

| Item | Current value | Unit | Caveat |
|---|---:|---|---|
| C0 generator fuel from residual WAG | 21.892922 | PJ_LHV/y | Development interface |
| C0 generator electricity | 2.067665 | TWh_e/y | 2.0 TWh is validation anchor only |
| C1 VN25 fuel | 9.759416 | PJ_LHV/y | Preferred anchor not fully met |
| C1 IJ01 fuel | 0.077195 | PJ_LHV/y | IJ01 split caveated |
| C1 generator preferred-anchor gap | 4.763389 | PJ_LHV/y | Mostly BFG shortfall |

No export revenue, no DA price response, no mFRR, and no direct WAG market value are active.

### Oxygen

| Item | C0 | C1 | Unit | Status |
|---|---:|---:|---|---|
| Total core oxygen demand | 893.438 | 982.144 | kt/y | development_reconciliation |
| ASU electricity | 357.375 | 392.857 | GWh_e/y | source_backed_current |
| DRP oxygen active basis | n/a | 0.135 | t O2/t DRI | sensitivity_required |
| DRP oxygen active equivalent | n/a | 94.472 | Nm3/t DRI | sensitivity_required |
| Vendor cross-check basis | n/a | 35 | Nm3/t DRI | sensitivity_required |

The DRP oxygen basis is one of the highest-impact review items. Current basis gives about `375.221 kt/y` DRP oxygen and about `150.088 GWh/y` ASU electricity. Vendor cross-check gives about `139.012 kt/y` DRP oxygen and about `55.605 GWh/y` ASU electricity.

### Steam

| Item | C0 | C1 | Unit | Status |
|---|---:|---:|---|---|
| Steam demand | 356.130613 | 165.461611 | kt/y | development_reconciliation |
| Steam supply | 356.130613 | 165.461611 | kt/y | development_reconciliation |
| Steam spill | 0 | 0 | kt/y | development_reconciliation |
| Unserved steam | 0 | 0 | kt/y | development_reconciliation |
| WAG to steam | 310.534 | 144.277 | GWh_LHV/y | development_reconciliation |

Steam is a mass-flow model, not an enthalpy model. Residual steam demand is deferred.

## F. Buffers And Stores

| Buffer/store | Current policy/value | Status | Review point |
|---|---|---|---|
| DRI buffer | C1 capacity 15.229653 kt; start/end 7.614826 kt; drift zero | development_reconciliation | Sensitise later |
| Coke/sinter/fired-pellet stores | Practically non-binding; bind count zero | modelling_policy | Not free sources |
| Slab/hot-cold scaffold | C5l_d `base_0_50` | development_reconciliation | Keep until denominator review |
| Hot-metal store | Inactive; 500 t candidate deferred | development_candidate | Do not activate now |
| Oxygen short buffer | 1670 m3 geometric anchor only; 100 t candidate deferred | development_candidate | Need pressure/usable swing |
| WAG holders | Not hourly stores | modelling_policy | No storage arbitrage |
| Steam | Bus/mass-flow balance; not store | modelling_policy | No steam storage |
| Liquid steel | Not intertemporal store | modelling_policy | No hidden buffering |
| Finished product | Accounting only | modelling_policy | Not denominator freeze |

## G. CO2 And Emissions Assumptions

CO2 is currently component diagnostic only. ETS-ready status is false.

| Component | C0 | C1 | Unit | Status |
|---|---:|---:|---|---|
| PEFA diagnostic CO2 | 0.452813 | 0.521140 | Mt/y | component_diagnostic_only |
| EAF midpoint CO2 | 0 | 0.422100 | Mt/y | range_midpoint_diagnostic |
| DRP capture stream | 0 | 0.794912 | Mt/y | capture_stream_not_direct_emissions |
| DSP direct CO2 | 0 | 0 | Mt/y | inactive_fuel_accounting_zero |

Deferred or blocked:

- WAG combustion/flaring CO2.
- NG combustion CO2.
- Scope 2 electricity CO2.
- Boiler/generator fuel-explicit CO2.
- Consolidated ETS-ready CO2 total.

Double-counting risks requiring policy:

- WAG carbon generation versus WAG combustion.
- PEFA/EAF aggregate diagnostics versus fuel-explicit accounting.
- DRP capture stream versus direct emissions.
- Coking direct CO2 versus COG carbon.

## H. Current High-Priority Review Questions

| No. | Question | Why it matters |
|---:|---|---|
| 1 | Is `6.75 Mt/y` acceptable as the active physical baseline, with `7.2/6.8 Mt/y` kept as validation context? | It fixes the comparison scale. |
| 2 | Should first economics report primarily per liquid-steel-equivalent/active target, with final-product proxy secondary? | It prevents a premature denominator freeze. |
| 3 | Is the C1 imported slab convention acceptable as validation/context until downstream denominator is fixed? | It affects product accounting and route comparability. |
| 4 | Is the EAF/DRP route split around `3.35 Mt/y` EAF and `3.4 Mt/y` BOF directionally acceptable? | It drives energy, WAG, oxygen and material balances. |
| 5 | Is the current EAF DRI coefficient `0.829675` acceptable as route reconciliation, or should `0.848` be enforced/sensitised? | It changes EAF/DRP material coupling. |
| 6 | Which DRP oxygen basis should be base or sensitivity: `0.135 t/t DRI` or `35 Nm3/t DRI`? | It materially changes oxygen and ASU electricity. |
| 7 | Is the C1 generator fuel gap acceptable as source-boundary caveat, or should WAG generation/self-use assumptions be reviewed first? | It affects electricity offsets and energy boundary credibility. |
| 8 | Can the C0 residual-WAG generator interface use a development efficiency of `0.34`? | It creates a large C0 internal electricity offset. |
| 9 | Do we have or need better plant-level electricity anchors for HSM/WBW, KGF, BF and BOF? | Residual electricity and Scope 2 are blocked without them. |
| 10 | Do we have or need better plant-level NG anchors for HSM/WBW, sinter, boilers and residual NG? | Residual NG and fuel CO2 are blocked without them. |
| 11 | Which CO2 boundary should be used first: component diagnostic only, direct+NG, or full WAG combustion policy? | It determines non-double-counting emissions accounting. |
| 12 | Are hot-metal store, oxygen numeric store, DRI buffer days and scrap pool correctly kept as sensitivity/deferred? | It prevents fake flexibility. |
| 13 | Are residual electricity/NG loads allowed later only after source-card repair? | It avoids using residuals as hidden calibration slack. |

## I. Assumptions Not To Change Without Methodological Decision

- No product revenue base objective.
- No generator export revenue.
- No mFRR.
- No DA/economics yet.
- No direct WAG market value.
- No full-site net import claim.
- No denominator freeze.
- No validation anchor as executable constraint.
- No WAG holders, steam, final-product accounting or liquid steel as stores.
- No residual electricity/NG loads before source-card repair.
- No full CO2 objective or ETS-ready total before carbon-boundary decision.

## J. Appendix Table

The machine-readable version is:

`data/03_Optimisation/inputs/assets/steel/S4/c5_assumption_review/c5_current_model_assumptions_for_review.csv`

| ID | Category | Short name | Current value or policy | Evidence | Priority |
|---|---|---|---|---|---|
| A001 | configuration | C0 definition | current BF-BOF reference with BF-BOF route only | modelling_policy | P1_review_before_thesis_results |
| A002 | configuration | C1 definition | Phase 1 hybrid BF-BOF plus NG-DRP plus EAF | modelling_policy | P1_review_before_thesis_results |
| A003 | configuration | C1 retained and inactive assets | BF6 and KGF1 retained; BF7 inactive; KGF2 inactive | modelling_policy | P0_review_before_economics |
| A004 | production | Active production target | 6.75 Mt liquid steel per year | development_reconciliation | P0_review_before_economics |
| A005 | production | Raw public LS anchors | C0 7.2; C1 6.8 Mt liquid steel per year | source_backed_validation_anchor | P0_review_before_economics |
| A006 | production | C1 route split | BOF 3.4; EAF 3.35; total 6.75 Mt liquid steel per year | development_reconciliation | P0_review_before_economics |
| A007 | production | Final-product proxy | C0 6.259091; C1 6.800535 Mt product proxy per year | development_reconciliation | P0_review_before_economics |
| A008 | production | Raw product anchors | C0 6.9; C1 7.0 Mt product proxy per year | source_backed_validation_anchor | P0_review_before_economics |
| A009 | materials | PEFA fired pellets | C0 4.3125; C1 4.963235 Mt/y | development_reconciliation | P1_review_before_thesis_results |
| A010 | materials | Imported pellets | C0 1.40625; C1 0.198529 Mt/y | development_reconciliation | P1_review_before_thesis_results |
| A011 | materials | BF pellet demand | C0 5.71875; C1 1.405803 Mt/y | development_reconciliation | P1_review_before_thesis_results |
| A012 | materials | DRP pellet demand | C1 3.755962 Mt/y | development_reconciliation | P1_review_before_thesis_results |
| A013 | materials | DRP DRI output | C1 2.7794116 Mt/y | development_reconciliation | P0_review_before_economics |
| A014 | materials | EAF DRI input | C1 2.7794116 Mt/y | development_reconciliation | P0_review_before_economics |
| A015 | materials | EAF DRI coefficient | Active 0.829675 versus source-review 0.848 t DRI/t LS | sensitivity_required | P0_review_before_economics |
| A016 | materials | EAF scrap input | C1 1.01505 Mt/y | development_reconciliation | P1_review_before_thesis_results |
| A017 | materials | Bounded coke reconciliation | C5m_f bounded coke reconciliation active; external coke fallback-only | development_reconciliation | P0_review_before_economics |
| A018 | materials | Bulk solid stores | Coke sinter fired-pellet stores practically non-binding; bind count zero | modelling_policy | P1_review_before_thesis_results |
| A019 | downstream | DSP output | 1.35 Mt/y in C0 and C1 | development_reconciliation | P0_review_before_economics |
| A020 | downstream | DSP LS input | About 1.4175 Mt liquid steel per year | development_reconciliation | P1_review_before_thesis_results |
| A021 | downstream | HSM/WBW scaffold | C5l_d base_0_50 preserved | development_reconciliation | P0_review_before_economics |
| A022 | downstream | C1 imported slab anchor | 0.6 Mt/y context | source_backed_validation_anchor | P0_review_before_economics |
| A023 | electricity | Modelled electricity demand before offsets | C0 1.742724; C1 3.03375 TWh_e/y | development_reconciliation | P0_review_before_economics |
| A024 | electricity | Major C1 electricity components | PEFA 0.105717; DRP 0.231525; EAF 1.4137; DSP 0.0756; ASU 0.392857 TWh_e/y | development_reconciliation | P0_review_before_economics |
| A025 | electricity | Generator and steam offsets | C0 2.100025 total offset; C1 0.950312 total offset TWh_e/y | development_reconciliation | P0_review_before_economics |
| A026 | electricity | C0 over-offset issue | C0 exposure floors at zero because offsets exceed modelled process demand | missing_anchor | P0_review_before_economics |
| A027 | electricity | C1 process exposure after offsets | 2.098472 TWh_e/y | development_reconciliation | P0_review_before_economics |
| A028 | natural_gas | C1 modelled NG | DRP 27.516175; EAF 0.1675; generator 4.1; total 31.783675 PJ_LHV/y | development_reconciliation | P0_review_before_economics |
| A029 | natural_gas | Zero backup NG in current run | Boiler steam NG 0; PEFA NG backup 0 PJ_LHV/y | development_reconciliation | P1_review_before_thesis_results |
| A030 | wag_generators | C0 residual-WAG generator interface | Fuel 21.892922 PJ/y; electricity 2.067665 TWh/y; 2.0 TWh validation anchor only | development_reconciliation | P0_review_before_economics |
| A031 | wag_generators | C1 generator fuel and gap | VN25 9.759416; IJ01 0.077195; gap 4.763389 mostly BFG PJ/y | sensitivity_required | P0_review_before_economics |
| A032 | wag_generators | WAG market value policy | No export revenue; no DA price response; no mFRR; no direct WAG market value | modelling_policy | P0_review_before_economics |
| A033 | oxygen | Total core oxygen demand | C0 893.438; C1 982.144 kt O2/y | development_reconciliation | P0_review_before_economics |
| A034 | oxygen | ASU electricity | C0 357.375; C1 392.857 GWh_e/y | source_backed_current | P1_review_before_thesis_results |
| A035 | oxygen | DRP oxygen basis | Current 0.135 t/t DRI equals 94.472 Nm3/t; vendor cross-check 35 Nm3/t equals 0.050 t/t | sensitivity_required | P0_review_before_economics |
| A036 | steam | Steam mass-flow balance | C0 demand/supply 356.130613; C1 demand/supply 165.461611 kt steam/y | development_reconciliation | P1_review_before_thesis_results |
| A037 | steam | WAG to steam | C0 310.534; C1 144.277 GWh_LHV/y | development_reconciliation | P1_review_before_thesis_results |
| A038 | buffers | DRI buffer | C1 capacity 15.229653 kt; start/end 7.614826 kt; drift zero | development_reconciliation | P2_sensitivity |
| A039 | buffers | Deferred or blocked stores | Hot-metal inactive; oxygen structural only; steam WAG liquid steel final product not stores | modelling_policy | P0_review_before_economics |
| A040 | co2 | CO2 boundary status | Component diagnostic only; ETS-ready false | blocked | P0_review_before_economics |
| A041 | co2 | Current component CO2 values | PEFA C0 0.452813; PEFA C1 0.521140; EAF C1 midpoint 0.4221; DRP capture 0.794912 Mt/y | development_reconciliation | P0_review_before_economics |
| A042 | co2 | Deferred CO2 components | WAG combustion/flaring CO2; NG combustion CO2; Scope 2; boiler/generator fuel CO2 deferred | deferred | P0_review_before_economics |
| A043 | residual_boundaries | Plant energy anchor gaps | KGF BF BOF HSM residual electricity weak; HSM residual NG and site residual NG missing | missing_anchor | P0_review_before_economics |
| A044 | governance | Forbidden current-scope changes | No product revenue base objective; no generator export revenue; no DA; no mFRR; no CVaR; no denominator freeze | modelling_policy | P0_review_before_economics |
