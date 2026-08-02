# Thesis Parameter and Source Register

## 1. Purpose and coverage

This register is the source-facing companion to `CORE_PHYSICAL_MILP.md`. It
contains every numerical value that should be stated in the main methodology
draft. It does not reproduce every zero coefficient, sparse topology entry,
solver option or diagnostic field in the executable model.

Every row has at least one provenance entry. Provenance is not always an
external measurement: validation-selected abstractions and governed
development assumptions are identified explicitly. They must not be presented
as Tata operating data merely because they have a traceable project source.

## 2. Evidence classes

| Class | Meaning | Permitted thesis wording |
|---|---|---|
| `SB` | Directly source-backed for the stated use and denominator | “obtained from” or “reported by” the source |
| `DV` | Transparently derived from a source-backed value | “derived from” with the conversion stated |
| `GP` | Governed development proxy supported by technical literature or modelling precedent | “assumed for the development model,” not “measured” |
| `VS` | Selected on validation and frozen before held-out evaluation | “validation-selected aggregate abstraction” |
| `UP` | Explicit user/project policy needed to define the represented boundary | “governed model assumption” |
| `VA` | Validation anchor only; not an executable constraint | “used for external comparison” |
| `DF` | Deferred or inactive value | Do not describe as active |

## 3. External source key

| Key | Source | Principal use |
|---|---|---|
| `S-JRC` | European Commission JRC, *Best Available Techniques Reference Document for Iron and Steel Production* (2013), [report](https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/IS_Adopted_03_2012.pdf) | Generic process coefficients and ranges; WAG properties; coke, sinter, pellet, BF and BOF context |
| `S-MER` | Royal HaskoningDHV for Tata Steel IJmuiden, *Detailstudie Energie en CO2-balans – MER Heracless – Groen Staal* (2025), [report](https://pas.commissiemer.nl/files/nl/3730/01-Energie.pdf) | C0/C1 site energy, WAG, NG, electricity and direct-CO2 anchors; DRP energy; steam and generator context |
| `S-HER` | Tata Steel Nederland/Royal HaskoningDHV, *MER Heracless – Deel B – Technische beschrijving* (2025), [report](https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf) | Configuration topology, closures, DRP/EAF, steam installations, generator operating-time context and HSM fuel topology |
| `S-ATH` | Athanasiadis, *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel’s IJmuiden Site* (TU Delft, 2025), [repository record](https://repository.tudelft.nl/record/7a0b891b-ceb8-4ceb-9d80-d0a5566dc618) | Process-network structure and figure-derived development bounds; DRP/EAF and buffer modelling precedent |
| `S-BAD` | Badarinath, *Optimising Industrial Participation in the Day-Ahead Electricity Market: A Stochastic Bidding Framework with Risk Management* (TU Delft, 2025), [repository record](https://repository.tudelft.nl/record/uuid%3A53243369-394e-4991-9c54-213fd5a07b1d) | Stochastic-bidding, non-anticipativity, risk and benchmark precedent; not numerical steel-plant evidence |
| `S-RVO` | Netherlands Enterprise Agency et al., *The Netherlands list of fuels and standard CO2 emission factors* (January 2025), [fuel list](https://english.rvo.nl/sites/default/files/2025-02/the-Netherlands-%20list-of-fuels-January-2025.pdf) | NCV/LHV-basis WAG and NG direct-combustion factors |
| `S-IEA` | IEA GHG/Swerea MEFOS, *Understanding the Techno-Economics of Deploying CO2 Capture Technologies in an Integrated Steel Mill* (2013), [report](https://ieaghg.org/publications/2013-04%20Iron%20and%20Steel%20CCS%20Study%20%28Techno-Economics%20Integrated%20Steel%20Mill%29.pdf) | Generic integrated-site power generation, WAG surplus and flare context |
| `S-TSN21` | Tata Steel Nederland/FNV-Zeester/Roland Berger, *Feasibility Study on Climate-Neutral Pathways for TSN IJmuiden* (2021), [report](https://products.tatasteelnederland.com/sites/producttsn/files/TSN%20Climate%20Neutral%20Pathways%20Final%20Report.pdf) | Transition-route and closure context |

The project has more sources than this compact key. The exact source-card and
evidence-register rows remain the audit layer; this table lists the sources
needed for the current thesis methodology.

## 4. Project-governance provenance key

| Key | Repository source | Role |
|---|---|---|
| `G-STATE` | `docs/optimisation/steel/S4/C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md` | Active state, objective order and promoted baseline |
| `G-FREEZE` | `docs/optimisation/steel/S4/C5_PHASE5K_FINAL_USER_AUTHORIZED_BOUNDARY_FREEZE_GATE.md` | Final represented-boundary parameters and held-out freeze |
| `G-DA` | `docs/optimisation/steel/S4/C6_PHASE6A_DETERMINISTIC_DA_BIDDING_SETTLEMENT_GATE.md` | Deterministic DA information and settlement contract |
| `G-CONFIG` | `scripts/Data/04_Steel_Test_Case/configs/steel_hourly_da_dplus4_point_forecast_integration.yaml` | Rolling horizon, production, material, generator and energy configuration |
| `G-P5K-CONFIG` | `scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5k_final_user_authorized_boundary_freeze.yaml` | Final selection grid and residual policy |
| `G-DEV` | `data/03_Optimisation/inputs/assets/steel/S4/s4_4b5a_asymmetric_c0_c1_correction/corrected_dev_inputs/` | Executable development bounds, conversions and store inputs |
| `G-COST` | `data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/c5_external_supply_costs.csv` | Governed development-price scenarios and original market-context links |
| `G-WAG` | `data/03_Optimisation/inputs/assets/steel/S4/c5_phase5k_final_user_authorized_boundary_contract/wag_carrier_source_audit.csv` | Active C0/C1 WAG yields, ranges and freeze decision |

## 5. Global, horizon and production parameters

| Parameter | Value | Unit | Class | Source(s)/provenance | Use and caveat |
|---|---:|---|---|---|---|
| Annual final-product target \(Q^{ann}\) | 6.75 million | t final product/y | `UP` | `G-STATE`, `G-CONFIG`; scenario context `S-MER` | Common C0/C1 denominator; scenario definition, not an observed annual dispatch constraint |
| Normal daily/block quota \(q^{blk}\) | 18,493.150685 | t final product/24-h block | `DV` | \(6.75\times10^6/365\); `G-CONFIG` | Carry-corrected in rolling execution |
| Planning horizon \(H_r\) | nominally 120 | h | `UP` | `G-CONFIG`, `G-DA` | D–D+4 contract; timestamp construction may yield 119/120/121 intervals around DST |
| Execution block \(B_r\) | nominally 24 | h | `UP` | `G-CONFIG`, `G-DA` | Only the first timestamp-defined day is executed |
| Representative-period replans | 7 | replans/period | `UP` | `G-CONFIG`, `G-FREEZE` | Produces a nominal 168-h executed period |
| Production-envelope tolerance | ±0.5 | % of cumulative reference | `UP` | `G-CONFIG`, `G-STATE` | Does not replace exact terminal quota or carry state |
| Procurement-optimum tolerance \(\tau^{cost}\) | 0.01 | EUR | `UP` | `G-STATE`; executable model builder | Numerical lexicographic preservation only |
| Progress-optimum tolerance \(\tau^{prog}\) | \(10^{-6}\) | t final product | `UP` | executable model builder; `G-STATE` | Numerical lexicographic preservation only |

## 6. Process activity bounds and topology

| Process | C0 active range | C1 active range | Activity unit | Class | Source(s)/provenance | Caveat |
|---|---:|---:|---|---|---|---|
| KGF1 | 150–180 | 150–180 | t dry coal input/h | `GP` | `S-ATH`; Coking Plants source card; `G-DEV` | Figure-derived operating proxy, not Tata control-room data |
| KGF2 | 150–180 | inactive | t dry coal input/h | `GP/UP` | KGF1 proxy in `G-DEV`; closure topology `S-HER`, `S-TSN21` | C0 capacity proxies KGF1; C1 inactivity is topology-backed |
| Sinter plant | 160–320 | 160–320 | t represented iron ore input/h | `GP` | `S-ATH`; SINTER source card; `G-DEV` | Development range, not an annual-to-hourly conversion |
| PEFA/pelletising | 300–565 | 300–565 | t represented iron ore input/h | `GP` | `S-ATH`; PELLETIZING source card; `G-DEV` | Modelled as continuous controller/activity layer |
| BF6 | 120–170 | 120–170 | t represented sinter input/h | `GP` | `S-ATH`; Blast Furnace source card; `G-DEV` | Figure-derived proxy; not measured BF6 operating limits |
| BF7 | 184.615–261.538 | inactive | t represented sinter input/h | `GP/UP` | BF6 proxy scaled using governed BF6/BF7 split in `G-DEV`; closure `S-HER` | Capacity proxy only; C1 inactivity is topology-backed |
| BOF/OSF | 505–830 | 505–830 | t hot-metal input/h | `GP` | `S-ATH`; BOF/OSF source card; `G-DEV` | Compact hourly development range |
| NG-DRP | inactive | 350–550 | t pellet input/h | `GP` | 0.7–1.1 times 500 t/h from `S-ATH`; DRP source card; `G-DEV` | Not a public Tata hourly limit |
| EAF | inactive | 360–440 | t DRI input/h | `GP` | 0.9–1.1 times 400 t/h from `S-ATH`; EAF source card; `G-DEV` | Semi-continuous development guardrail |
| HSM/WBW | 145–800 | 145–800 | t slab input/h | `GP` | `S-ATH`; HSM source card; `G-DEV` | Figure-derived proxy; C0/C1 fuel policies differ |

Source-classified continuous assets remain available with endogenous bounded
throughput. These ranges must not be called ramp limits or outage schedules.

## 7. Material conversion and route parameters

| Parameter | Value | Unit | Class | Source(s)/provenance | Use and caveat |
|---|---:|---|---|---|---|
| Dry coal per coke | 1.285 | t dry coal/t coke | `GP` | `S-JRC`; Coking Plants source card; `G-CONFIG` | Central compact coke-yield coefficient within documented range |
| Coke per hot metal | 0.359 | t coke/t HM | `GP` | `S-JRC`; Blast Furnace source card; `G-CONFIG` | Represented coke input; PCI remains separate |
| Sinter ore input | 0.813 | t represented ore/t sinter | `GP` | SINTER source card, Gate-1 conversion; generic context `S-JRC` | Omitted raw-mix additions are implicit |
| Sinter output reciprocal | 1.230 | t sinter/t represented ore-bus input | `DV` | Reciprocal of 0.813; SINTER source card; `G-CONFIG` | Output exceeds represented ore because other burden inputs are outside bus 0 |
| BF represented conversion | 2.1041667 | t HM/t represented sinter-bus input | `GP` | governed C5 bus conversion in `G-DEV`; Blast Furnace source card | Compact model-bus relationship, not a full physical burden balance |
| C0 BOF hot metal | 0.875 | t HM/t BOF liquid steel | `GP` | BOF/OSF source card; `G-CONFIG`; route context `S-MER` | Compact metallics recipe |
| C0 BOF scrap | 0.208 | t scrap/t BOF liquid steel | `GP` | BOF/OSF source card; `G-CONFIG` | Other additions/losses are outside the compact balance |
| C1 BOF hot metal | 0.824 | t HM/t BOF liquid steel | `GP` | BOF/OSF source card; `G-CONFIG`; C1 context `S-HER` | Compact C1 retained-route recipe |
| C1 BOF scrap | 0.294 | t scrap/t BOF liquid steel | `GP` | BOF/OSF source card; `G-CONFIG` | Route-specific cap also applies |
| EAF HDRI input | 0.84848485 | t HDRI/t EAF liquid steel | `GP` | EAF source card; `S-ATH`; `G-CONFIG` | Compact metallics coefficient |
| EAF scrap input | 0.27272727 | t scrap/t EAF liquid steel | `GP` | EAF source card; `S-ATH`; `G-CONFIG` | Remaining additions and losses are omitted |
| HSM slab input | 1.06 | t slab/t HRC | `GP` | HSM source card; `G-CONFIG`; downstream context `S-HER` | Compact casting/rolling yield |
| DSP liquid-steel input | 1.05 | t liquid steel/t coil | `GP` | DSP source card; `G-CONFIG`; route context `S-HER` | Modelling assumption supported by casting-yield literature, not Tata-measured |
| Site scrap cap | 1.9 million | t/y equivalent | `UP` | scrap supply ledger in `G-CONFIG` | Cumulative rolling cap, not hourly delivery schedule |
| BOF scrap cap | 1.0 million | t/y equivalent | `UP` | scrap supply ledger in `G-CONFIG` | Separate route guardrail |
| EAF scrap cap | 1.8 million | t/y equivalent | `UP` | scrap supply ledger in `G-CONFIG` | Separate route guardrail |
| Imported-slab cap | 0.6 million | t/y equivalent | `UP` | `G-CONFIG`; C1 boundary context `S-MER` | Imported slab can enter only the governed downstream route |

## 8. Material-store parameters

| Store | Configuration | Capacity | Initial level | Terminal level | Unit | Class | Source(s)/provenance | Caveat |
|---|---|---:|---:|---:|---|---|---|---|
| Coke | C0 | 720 | 360 | 360 | t | `GP` | `S-ATH`; BUFFERS/STORAGE source card; `G-DEV` | Figure-derived development store |
| Coke | C1 | 360 | 180 | 180 | t | `GP` | retained-route scaling in `G-DEV`; BUFFERS/STORAGE source card | Development value |
| Sinter | C0/C1 | 640 | 320 | 320 | t | `GP` | `S-ATH`; BUFFERS/STORAGE source card; `G-DEV` | Figure-derived development store |
| Hot metal | C0/C1 | 500 | 250 | 250 | t HM | `GP` | `S-ATH`; BUFFERS/STORAGE source card; `G-DEV` | Figure-derived development store |
| Cold slab | C0/C1 | 25,000 | 12,500 | 12,500 | t slab | `GP` | `S-ATH`; HSM slab-buffer and BUFFERS/STORAGE source cards; `G-DEV` | Shared downstream development store; active terminal equality |
| DRI | C1 | 17,760 | 0 | 0 | t DRI | `GP` | two-day decoupling precedent `S-ATH`/`S-BAD`; DRP source card; `G-DEV` | Public MER confirms silos but not this numerical capacity |

All listed stores use zero standing loss in the active development input. Equal
initial and terminal levels, or the explicit zero DRI endpoint, enforce the
no-free-buffer-battery policy.

## 9. Process electricity, fuel and oxygen parameters

| Process/service parameter | Value | Unit | Class | Source(s)/provenance | Caveat |
|---|---:|---|---|---|---|
| KGF purchased electricity | 0.0667 | MWh\(_e\)/t coke | `GP` | Coking Plants source card; candidate overlay; generic LCI context | Converted from 0.24 GJ/t; non-Tata value |
| KGF underfiring heat | 3.5 | GJ\(_{LHV}\)/t coke | `GP` | Coking Plants source card; generic range `S-JRC`; executable model builder | Active rounded development coefficient; carrier eligibility is handled separately |
| Sinter electricity | 0.0343 | MWh\(_e\)/t sinter | `GP` | SINTER source card; `S-JRC` | Active on converted sinter output |
| Sinter COG heat | 0.067 | GJ\(_{LHV}\)/t sinter | `GP` | SINTER source card; `S-JRC` | Carrier-specific heat demand |
| PEFA electricity | 0.0213 | MWh\(_e\)/t pellets | `DV` | midpoint of JRC 0.0150–0.0275 range; PELLETIZING source card; `S-JRC` | Development midpoint, not Tata measurement |
| PEFA total gas heat | 0.320 | GJ\(_{LHV}\)/t pellets | `DV/GP` | 0.306 GJ COG/BOFG + 0.014 GJ NG from `S-JRC`; PELLETIZING source card; controller contract | Active controller lineage uses governed COG/BOFG site allocations; NG is eligible backup |
| PEFA solid fuel | 0.342 | GJ/t pellets | `GP` | `S-JRC`, Table 4.1; PELLETIZING source card; controller contract | Non-WAG process-energy term; not a flexible fuel store |
| BF hot-stove heat | 2.20 | GJ\(_{LHV}\)/t HM | `GP` | Blast Furnace source card; controller contract; generic context `S-JRC` | BFG-first; no Wobbe layer |
| BF electricity | 0.0744 | MWh\(_e\)/t HM | `GP` | Blast Furnace source card and controller parameter register; `S-JRC` context | Development coefficient |
| BF oxygen | 54.4 | kg O2/t HM | `GP` | Blast Furnace source card and controller parameter register; `S-JRC` context | Development coefficient |
| BOF electricity | 0.0268 | MWh\(_e\)/t liquid steel | `GP` | BOF/OSF source card and parameter register; generic literature therein | Candidate, not Tata-validated |
| BOF oxygen | 78.6 | kg O2/t liquid steel | `GP` | BOF/OSF source card and parameter register; generic literature therein | Equivalent candidate row also records 55 Nm3/t |
| DRP NG reduction | 8.1 | GJ\(_{LHV}\)/t DRI | `SB` | `S-MER`; DRP source card | Tata/MER Phase-1 basis |
| DRP NG process furnace | 1.8 | GJ\(_{LHV}\)/t DRI | `SB` | `S-MER`; DRP source card | Tata/MER Phase-1 basis |
| DRP total NG | 9.9 | GJ\(_{LHV}\)/t DRI | `DV` | 8.1 + 1.8 from `S-MER`; DRP source card | Active source-backed sum |
| DRP electricity | 0.083333 | MWh\(_e\)/t DRI | `DV` | 0.3 GJ/t divided by 3.6; `S-MER`; DRP source card | Active value |
| EAF arc electricity | 0.422222 | MWh\(_e\)/t liquid steel | `DV` | 1.52 GJ/t divided by 3.6; `S-MER`; EAF source card | Active arc-energy term |
| EAF secondary electricity | 0.031 | MWh\(_e\)/t liquid steel | `GP` | EAF source card; `S-ATH`; `G-CONFIG` | Development secondary-services term |
| EAF NG | 0.05 | GJ\(_{LHV}\)/t liquid steel | `SB/GP` | `S-MER`; EAF source card; `G-CONFIG` | Active represented burner term |
| HSM reheating | 1.35 | GJ\(_{LHV}\)/t HRC | `GP` | HSM source card; controller contract; generic rolling literature | Development central heat demand |
| HSM rolling electricity | 0.070 | MWh\(_e\)/t HRC | `GP` | HSM source card; controller contract | Development value; not DA-responsive by itself |
| DSP electricity | 0.056 | MWh\(_e\)/t coil | `GP` | DSP source card; development input register | Development rolling/casting coefficient |
| ASU electricity | 0.400 | MWh\(_e\)/t gaseous O2 | `GP` | LINDE/OXYGEN source card and development register | Represents selected gaseous-O2 production, not full Linde electricity |
| C1 N2 auxiliary | 45 | MW\(_e\) | `GP` | LINDE/OXYGEN source card; `G-CONFIG` | Fixed auxiliary context, not a flexible ASU dispatch variable |
| NG lower heating value | 35.8 | MJ/Nm3 | `SB` | `S-MER`/governed gas parameter register; `G-CONFIG` | Used for volume-energy conversions where required |

## 10. WAG generation and quality parameters

| Carrier | Driver | Original coefficient | C0 active | C1 active | Unit | LHV | Class | Source(s)/provenance |
|---|---|---:|---:|---:|---|---:|---|---|
| BFG | Hot metal | 1,600 | 1,520 | 1,600 | Nm3/t HM | 3.85 MJ/Nm3 | `GP/UP` | Yield/range `S-JRC`, `S-ATH`; C0 0.95 policy `G-WAG`, `G-FREEZE` |
| COG | Dry-coal input | 365 | 346.75 | 365 | m3/t dry coal | 18.5 MJ/Nm3 | `GP/UP` | Yield/range `S-JRC`, `S-ATH`; C0 0.95 policy `G-WAG`, `G-FREEZE` |
| BOFG | BOF liquid steel | 75 | 71.25 | 75 | Nm3/t liquid steel | 8.6 MJ/Nm3 | `GP/UP` | Yield/range `S-JRC`, `S-ATH`; C0 0.95 policy `G-WAG`, `G-FREEZE` |

The 0.95 C0 multiplier is a user-authorized represented-boundary fallback. It
is not a source-identified carrier correction and must be described as such.
WAG lower heating values are generic central values inside documented ranges,
not measured hourly gas quality.

## 11. HSM fuel-source policy

| Configuration | NG share | COG share | Basis | Enforcement | Class | Source(s)/provenance | Caveat |
|---|---:|---:|---|---|---|---|---|
| C0 | 0.45 | 0.55 | volumetric design-flow share | exact over 24-h block | `UP` | QRA/source topology summarized in HSM source card; Phase-5F/5G policy; `G-FREEZE` | Model policy, not observed annual consumption split |
| C1 | 0.80 | 0.20 | volumetric design-flow share | exact over 24-h block | `UP` | QRA/Heracless topology `S-HER`; HSM source card; `G-FREEZE` | BFG and BOFG excluded from active HSM mix |

## 12. Steam and boiler parameters

| Parameter | C0 | C1 | Unit | Class | Source(s)/provenance | Caveat |
|---|---:|---:|---|---|---|---|
| Represented 15-bar demand \(S_c^{dem}\) | 40.654180 | 18.888312 | t steam/h | `GP` | boiler/steam accounting lineage; BOILER_STEAM source card; topology `S-MER` | Existing process load mapped to 15 bar by assumption |
| Annual-equivalent demand | 356.130613 | 165.461611 | kt steam/y | `DV` | hourly demand times 8,760; same sources | Representative accounting value |
| Effective fuel/steam coefficient \(\kappa^{steam}\) | 0.872 approx. | 0.872 approx. | MWh\(_{LHV}\)/t steam | `DV/GP` | boiler fuel allocation divided by steam demand; BOILER_STEAM source card | Source-table accounting ratio, not measured efficiency |
| Residual steam | 0 | 0 | t/h | `UP` | `G-FREEZE` | Inactive; no whole-site steam closure claim |

Unit-level source-table context is retained but is not independent active
dispatch in the frozen core:

| Installation | Steam capacity | Thermal/electrical context | Class | Source(s) | Active interpretation |
|---|---:|---|---|---|---|
| K15 | 110 t/h | 96.4 MWth | `SB` | `S-MER`, BOILER_STEAM source card | Aggregated boiler context |
| K16 | 110 t/h | 96.4 MWth | `SB` | `S-MER`, BOILER_STEAM source card | Aggregated boiler context |
| K23 | 110 t/h | 96.2 MWth | `SB` | `S-MER`, BOILER_STEAM source card | Aggregated boiler context |
| K24 | 110 t/h | 93.1 MWth | `SB` | `S-MER`, BOILER_STEAM source card | Aggregated boiler context |
| K41 | 80 t/h | 56 MWth | `SB` | `S-MER`, BOILER_STEAM source card | Aggregated boiler context |
| STEG11 | 80 t/h | 85 MWth; 13.1 MWe | `SB` | `S-MER`, BOILER_STEAM source card | Accounting/topology, no DA or mFRR revenue |
| TG2 | 105 t/h | 14.5 MWe; 0.138 MWh/t steam | `SB/DV` | `S-MER`, BOILER_STEAM source card | Accounting/topology, no DA or mFRR revenue |

## 13. Generator parameters

| Interface | Parameter | Value | Unit | Class | Source(s)/provenance | Caveat |
|---|---|---:|---|---|---|---|
| C0 aggregate | Total gas-volume cap | 900,000 | Nm3/h | `GP` | generator source card; aggregate C0 interface contract; `S-MER` context | Development technical envelope |
| C0 aggregate | Electricity cap | 770 | MW\(_e\) | `GP` | generator source card; Phase-5B/5G interface | Not a measured unit-dispatch limit |
| VN25 | Gas-volume cap | 600,000 | Nm3/h | `GP` | generator source card; `G-CONFIG`; `S-MER` context | Development interface |
| VN25 | Electricity cap | 350 | MW\(_e\) | `GP` | generator source card; `G-CONFIG`; `G-STATE` | Zero-to-upper-bound abstraction; no minimum load/ramp/start logic |
| VN25 | Electrical efficiency | 0.345 | MWh\(_e\)/MWh\(_{LHV}\) | `GP` | generator source card; `G-CONFIG`; generic cross-check `S-IEA` | Constant development efficiency |
| IJ01 | Gas-volume cap | 300,000 | Nm3/h | `GP` | generator source card; `G-CONFIG`; `S-MER` context | No invented electrical efficiency |
| VN25/IJ01 | Operating-time context | 85/15 | % of operating time | `SB` | `S-HER`, generator source card | Must not be interpreted as electricity-output allocation |
| All generators | Electricity export | 0 | MW\(_e\) | `UP` | `G-FREEZE`, `G-DA` | No export revenue or market sale |

## 14. Final represented-boundary parameters

| Parameter | C0 | C1 | Unit | Class | Source(s)/provenance | Caveat |
|---|---:|---:|---|---|---|---|
| Constant electricity background \(P_c^{base}\) | 141.370467 | 157.847548 | MW\(_e\) | `VS` | 90% validation selection in `G-FREEZE`; annual anchors `S-MER` | Fixed net demand, not observed hourly profile or flexible load |
| Annual electricity background | 4.458259 | 4.977880 | PJ/y | `DV` | hourly value times 8,760; `G-FREEZE` | Same boundary abstraction |
| Constant site NG service \(N_c^{base}\) | 221.968544 | 221.968544 | MWh\(_{LHV}\)/h | `UP` | `G-FREEZE`, `G-P5K-CONFIG`; anchor context `S-MER` | Fixed external purchase, costed once, not allocated to a plant and not WAG-displaceable |
| Annual site NG service | 7.0 | 7.0 | PJ/y | `UP` | `G-FREEZE` | Same absolute service in C0 and C1 |
| Residual direct CO2 | 2.0 | 2.0 | MtCO2/y | `VS` | Predeclared validation grid in `G-P5K-CONFIG`; selected in `G-FREEZE`; anchors `S-MER` | Reporting only; excluded from dispatch, cost and ETS |

## 15. Procurement-price parameters

| External flow | Central value | Unit | Class | Source(s)/provenance | Caveat |
|---|---:|---|---|---|---|
| Flat grid electricity | 80 | EUR/MWh\(_e\) | `GP` | `G-COST`; EPEX market-results context linked there | Development reference, not an observation date or Tata tariff |
| Natural gas | 55 | EUR/MWh\(_{LHV}\) | `GP` | `G-COST`; ACER gas-market context linked there | Excludes taxes, network costs and Tata contract terms |
| Dry coking coal | 205 | EUR/t purchased dry coal | `GP` | `G-COST`; S&P HCC benchmark context linked there | Not delivered-IJmuiden contract price |
| PCI | 145 | EUR/t purchased PCI | `GP` | `G-COST`; public coal benchmark context linked there | Thermal-coal benchmarks are imperfect PCI proxies |
| Represented iron ore | 90 | EUR/t purchased ore | `GP` | `G-COST`; S&P iron-ore methodology linked there | Grade and delivery basis remain proxies |
| Imported DR pellets | 180 | EUR/t imported DR pellets | `GP` | `G-COST`; iron-ore/pellet benchmark context linked there | DR-grade delivered quality remains a proxy |
| Purchased scrap | 330 | EUR/t purchased scrap | `GP` | `G-COST`; LME/market context linked there | Site-boundary scrap is represented as purchased once |
| Imported slab | 530 | EUR/t imported slab | `UP/GP` | `G-COST` | No exact governed public locator; explicitly a development value |

The active BF-pellet price, HBI price, quicklime price and EUA price rows are
inactive or deferred and should not be included in the current objective.

## 16. Direct-emissions parameters

| Fuel/carrier | Factor | Unit | Class | Source(s)/provenance | Use and caveat |
|---|---:|---|---|---|---|
| BFG | 247.4 | kgCO2/GJ\(_{LHV}\) | `SB` | `S-RVO`; WAG/CO2 source card | Count once at represented oxidation or flare sink |
| COG | 42.8 | kgCO2/GJ\(_{LHV}\) | `SB` | `S-RVO`; WAG/CO2 source card | Count once at represented oxidation or flare sink |
| BOFG | 191.9 | kgCO2/GJ\(_{LHV}\) | `SB` | `S-RVO`; WAG/CO2 source card | BOFG/LDG mapping retained explicitly |
| Natural gas | 56.1 | kgCO2/GJ\(_{LHV}\) | `SB` | `S-RVO`; governed carrier register; `G-P5K-CONFIG` | Apply only to represented named NG combustion |

The active emissions mode is point of oxidation. Aggregate process-counter CO2
must not be added to the same carrier-explicit total. Scope 2 and ETS cost are
outside the current formulation.

## 17. Validation anchors, not model constraints

| Annual metric | C0 anchor | C1 anchor | Unit | Class | Source | Use |
|---|---:|---:|---|---|---|---|
| Gross electricity | 13.7 | 17.8 | PJ/y | `VA` | `S-MER`, Table 6.6 | External annual-equivalent comparison |
| Natural gas | 12.5 | 46.7 | PJ/y | `VA` | `S-MER`, Table 6.6 | External annual-equivalent comparison |
| BFG production | 33.2 | 14.8 | PJ/y | `VA` | `S-MER`, Table 6.5 | Carrier-specific comparison |
| COG production | 14.7 | 8.1 | PJ/y | `VA` | `S-MER`, Table 6.5 | Carrier-specific comparison |
| BOFG production | 5.0 | 2.2 | PJ/y | `VA` | `S-MER`, Table 6.5 | Carrier-specific comparison |
| Direct Scope-1 context | 12.6 | 8.3 | MtCO2/y | `VA` | `S-MER`, Table 6.7 | Partial-boundary comparison; not ETS closure |

## 18. Source-card audit paths

The plant-specific evidence, alternative ranges and excluded values are kept
in:

- `data/03_Optimisation/inputs/assets/steel/source_cards/Coking_Plants_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/SINTER_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/PELLETIZING_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/Blast_Furnace_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/BOF_OSF_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/DRP_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/EAF_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/HSM_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/HSM_Slab_Buffer_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/DSP_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/LINDE_OXYGEN_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/BOILER_STEAM_CIRCUIT_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/IJ01_VN25_GENERATORS_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/WAG_CARRIERS_CO2_FACTORS_Parameters.md`
- `data/03_Optimisation/inputs/assets/steel/source_cards/BUFFERS_STORAGE_Parameters.md`

## 19. Later-extension parameter provenance

The following parameters do not yet have promoted numerical values in the
steel model. Their methodological or data provenance is nevertheless fixed so
that a later chapter does not introduce unsourced symbols.

| Extension parameter | Numerical status | Required source/provenance | Methodological use and caveat |
|---|---|---|---|
| Deterministic point forecast \(\widehat\pi_{r,t}^{DA}\) | Active time series, not a scalar | `G-DA`; governed LEAR D–D+4 forecast contract; `docs/forecasting/strict_lear_hourly_qh_dplus4_finalisation.md` | Only forecasts available before submission enter optimisation |
| Realised DA price \(\pi_t^{real}\) | Ex-post time series | `G-DA`; governed Dutch price source plus fingerprinted Fraunhofer Energy-Charts supplement for identified gaps | Settlement and oracle only; never executable information |
| Scenario price \(\pi_{t,\omega}^{DA}\) | Not yet promoted | Phase-6B scenario contract when frozen; scenario-method precedent `S-BAD`; forecasting-method guardrails | Must preserve multihour dependence and information timing |
| Scenario probability \(p_\omega\) | Not yet promoted | Same Phase-6B scenario-generation and reduction contract; `S-BAD` | Required, non-negative and normalized; not assumed uniform unless validated and declared |
| CVaR confidence \(\alpha\) | Not yet selected | Validation-based selection under `docs/optimisation/METHODOLOGICAL_GUARDRAILS.md`; risk precedent `S-BAD` | Must not be selected on final test results |
| CVaR weight \(\lambda^{risk}\) | Not yet selected | Same validation policy and `S-BAD` | Economic-risk preference, not a physical steel parameter |
| mFRR capacity price \(\pi_t^{cap,a}\) | Not active | TenneT source documents and governed interpretation in `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md` | Version and product timing must be frozen at implementation |
| mFRR activation price \(\pi_{t,\omega}^{act,a}\) | Not active | TenneT MARI standard-mFRR handbook and governed market-rule document | Scenario/time series; sign convention must be explicit |
| Imbalance price \(\pi_{t,\omega}^{imb}\) | Not active | TenneT imbalance-pricing documentation and governed market-rule document | Settlement parameter, not a production coefficient |
| Non-delivery penalty \(\pi^{ndel}\) | Not active | Applicable TenneT BSP/manual terms at the future implementation date | Must not be invented or copied from an obsolete product version |
| Activation fraction \(\zeta_{t,\omega}^{a}\) | Not active | Future mFRR activation-scenario contract based on TenneT product data/rules | Scenario parameter; probabilities and timing required |
| Reserve headroom \(\overline H_t^a\) | Not active | Derived from the frozen core MILP and a future validated reserve-envelope contract | Endogenous physical limit; not a market-data input |

The source documents currently retained for the market-rule interpretation are
under `docs/market_rules/source_documents/`. Because market rules can change,
the future implementation gate must verify that those versions are still the
correct versions for the modelled delivery period.
