# DSP / Direct Sheet Plant Parameter Source Card

## Purpose

This note records a compact, source-backed candidate parameter set for the **Direct Sheet Plant (DSP)** in the public Tata Steel IJmuiden-inspired steel model.

It follows the same governance logic as the previous plant notes:

- source evidence, modelling interpretation, candidate values, validation anchors, derived values, and deferred details remain separate;
- values in this note are **not automatically executable model inputs**;
- annual volumes are **validation anchors**, not hourly dispatch constraints;
- the DSP is included as a downstream physical production route because it materially affects the final-product target and liquid-steel routing.

The intended first implementation is simple:

```text
liquid_steel_to_DSP + electricity -> DSP_hot_rolled_coils
```

A tunnel-furnace / thermal equalisation heat term is recognised structurally, but should remain deferred or sensitivity-only unless a stronger public Tata-specific value is approved.

---

## 1. Model interpretation

The Direct Sheet Plant is a downstream finishing plant that transforms liquid steel into hot-rolled coil in a continuous casting-and-rolling route. In the Tata/MER description, liquid steel from the Oxystaalfabriek can be sent directly to the DSP, while the remaining steel is cast into slabs and routed to the Warmbandwalserij (HSM/WBW). The DSP is therefore not a WAG-producing plant and should not be treated as a fuel-gas source.

For the first model stage, the DSP should be represented as a compact downstream Link:

```text
P_DSP[t] = DSP_hot_rolled_coil_output[t]       # t DSP coil/h

liquid_steel_input[t] = P_DSP[t] * DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL
electricity[t]        = P_DSP[t] * DSP_ELECTRICITY_MWH_PER_T_COIL
co2_direct[t]         = fuel-derived only if a DSP heat/fuel term is explicitly active
```

Recommended base structure:

```text
DSP_OUTPUT_BASIS = t DSP hot-rolled coil
DSP_FUEL_GAS_BASE_ACTIVE = false
DSP_TUNNEL_FURNACE_HEAT = deferred / sensitivity only
DSP_DIRECT_CO2_MODE = derived_from_active_fuel_only
```

The reason is methodological: public sources support DSP topology and output anchors well, but do not provide a robust Tata-specific fuel or tunnel-furnace heat coefficient. Adding a gas demand without support would create an artificial WAG sink.

---

## 2. Source hierarchy

| Rank | Source | Role | Certainty / caveat |
|---:|---|---|---|
| 1 | Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025), *MER Heracless – Groen Staal, Deel B: Technische beschrijving* | Tata-specific DSP topology, role, C0/C1 production anchors, 20% route statement, C1 unchanged process statement, EAF-route share. | High for public topology and annual anchors; not a conversion-factor table. |
| 2 | Tata Steel Nederland, *Plants* webpage | Current public plant fact sheet: DSP annual production and tunnel furnace length. | Useful public plant fact sheet; not a modelling input table. |
| 3 | Kromhout et al. (2008), *Mould Powder Requirements for High-speed Casting* | Technical DSP specifications: thin slab casting speed, slab thickness, strip dimensions, capacity. | Good Corus/IJmuiden-specific technical context; not an energy table. |
| 4 | European Commission (2022), *BAT conclusions for the ferrous metals processing industry* and JRC FMP BREF | Generic hot rolling electricity / rolling-energy ranges and hot/direct charging caveats. | High-quality generic technology evidence, not Tata-DSP-specific. |
| 5 | Worrell et al. / LBNL (2008), *World Best Practice Energy Intensity Values for Selected Industrial Sectors* | Best-practice sanity check for thin slab casting and rolling final energy. | Useful order-of-magnitude check; technology-generic. |
| 6 | Athanasiadis (2025) and Badarinath (2025) | Modelling precedent: DSP and HSM as parallel final coiled-steel targets; downstream flexibility constrained by slab/liquid-steel routing. | Modelling precedent only; not exact Tata public parameter truth. |

---

## 3. Compact parameter set

### 3.1 Topology, activity basis and output anchors

| Parameter ID | Value / range | Unit | Status | Source(s) | Interpretation / caveat |
|---|---:|---|---|---|---|
| `DSP_OUTPUT_BASIS` | DSP hot-rolled coil / DSP rolls | t coil | modelling choice | MER Heracless; Tata Plants page | Use final DSP coil output as activity basis. |
| `DSP_C0_OUTPUT_ANNUAL_MT_Y` | 1.5 | Mt/y | validation anchor | MER Heracless, Section 4.3, material outputs | Reference-situation DSP-roll output; losses already removed from output volumes. |
| `DSP_C1_OUTPUT_ANNUAL_MT_Y` | 1.5 | Mt/y | validation anchor | MER Heracless, Section 13.7 | DSP production remains max. 1.5 Mt/y and the process does not change. |
| `DSP_PUBLIC_CAPACITY_MT_Y` | 1.4 | Mt/y | external/current public check | Tata Steel Nederland, *Plants* webpage | Public plant fact sheet gives 1.4 Mt/y and 70,000 rolls/y. Use as public-current context; MER anchor controls Heracless modelling. |
| `DSP_TECHNICAL_CAPACITY_MT_Y_CORUS` | 1.3 | Mt/y | technical historical check | Kromhout et al. (2008), Table 1 | Historic Corus DSP capacity in technical paper; useful sanity check, not current anchor. |
| `DSP_C0_SHARE_OF_OSF_TO_DSP` | 0.20 | fraction | validation / routing anchor | MER Heracless, Section 3.5 | 20% of steel from OSF goes liquid-state to DSP; 80% as slabs to WBW/HSM. |
| `DSP_C1_EAF_ROUTE_SHARE_OF_DSP` | approx. 0.90 | fraction | validation / routing anchor | MER Heracless, Section 13.7 | About 90% of steel processed in the DSP is expected to come from the EAF route. This is a route-share anchor, not a dispatch constraint. |
| `DSP_PROCESS_CHANGED_IN_C1` | false | bool | topology anchor | MER Heracless, Section 13.7 | Existing DSP remains structurally unchanged in Heracless. |
| `DSP_ALLOWED_INPUT_C0` | BOF/OSF liquid steel | carrier | base structure | MER Heracless, Sections 3.4 and 3.5 | First model can use liquid-steel pool or route-specific BOF liquid steel. |
| `DSP_ALLOWED_INPUT_C1` | BOF/OSF liquid steel + EAF-route liquid steel | carrier | base structure | MER Heracless, Section 13.7 | DSP can process output from both routes; 90% EAF-route anchor should be reported separately. |

### 3.2 Material conversion and yield

| Parameter ID | Value / range | Unit | Status | Source(s) | Interpretation / caveat |
|---|---:|---|---|---|---|
| `DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL_BASE` | 1.05 | t liquid steel / t DSP coil | base candidate / modelling assumption | Van Wees (1986) for continuous casting and hot strip yield sanity; MER output losses note | Compact yield assumption for first model. Not Tata-validated. |
| `DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL_RANGE` | 1.03–1.07 | t liquid steel / t DSP coil | sensitivity range | Van Wees (1986); MER Section 4.3 | Lower bound aligns with continuous casting material ratio; upper bound allows rolling/cutting losses. |
| `DSP_COIL_YIELD_T_PER_T_LS_DERIVED` | 0.952 | t coil / t liquid steel | derived | inverse of base candidate | Derived value only; do not source separately. |
| `DSP_INTERNAL_SCRAP_LOSS_T_PER_T_COIL_DERIVED` | 0.05 | t/t coil | derived / reporting | from base liquid-steel input assumption | Route loss / cutting loss should return to internal scrap if that loop is active. Do not hide it as disappearing material. |
| `DSP_INTERNAL_SCRAP_RECYCLED` | true | bool | topology / reporting | MER Section 3.5 and 4.3 | MER states rolling losses such as cutting losses are already removed from end-product volumes and enter internal scrap stream. |

### 3.3 Electricity and heat

| Parameter ID | Value / range | Unit | Status | Source(s) | Interpretation / caveat |
|---|---:|---|---|---|---|
| `DSP_ELECTRICITY_MWH_PER_T_COIL_BASE` | 0.056 | MWh/t coil | base candidate | Worrell et al. / LBNL (2008); EC BAT conclusions rolling-energy range | Matches 0.20 GJ/t best-practice thin-slab casting and rolling as an order-of-magnitude aggregate, and lies inside the EU rolling-energy range. |
| `DSP_ELECTRICITY_MWH_PER_T_COIL_RANGE` | 0.028–0.111 | MWh/t coil | sensitivity / generic technology range | EC BAT conclusions for hot rolling, Table 1.22 | Generic hot-rolling specific rolling energy range, not DSP-specific. Use for sensitivity. |
| `DSP_TOTAL_FINAL_ENERGY_GJ_PER_T_BEST_PRACTICE` | 0.20 | GJ/t steel | sanity check | Worrell et al. / LBNL (2008), Section 2.1.6 | Final energy for casting and rolling using thin slab casting. Use as cross-check, not as separate additive energy if electricity is already active. |
| `DSP_TUNNEL_FURNACE_PRESENT` | true | bool | topology | Tata Plants page; Kromhout et al. (2008); DSP technical papers | DSP has a tunnel furnace / direct sheet route. Do not infer fuel demand without a supported coefficient. |
| `DSP_TUNNEL_FURNACE_LENGTH_M` | 320 | m | technical context | Tata Plants page | Plant fact-sheet value; not an energy coefficient. |
| `DSP_TUNNEL_FURNACE_HEAT_GJ_PER_T` | deferred | GJ/t coil | deferred detail | no robust public Tata coefficient found | Do not create a WAG/NG sink from this until a source-backed value is approved. |
| `DSP_FUEL_GAS_BASE_ACTIVE` | false | bool | modelling policy | evidence limitation + WAG governance | Avoid fake WAG demand. Fuel/gas heat may be added later as sensitivity if source-backed. |
| `DSP_ALLOWED_FUEL_CARRIERS_IF_HEAT_ACTIVE` | COG, BFG, BOFG, NG | carriers | deferred eligibility | generic FMP / site WAG context | Eligibility only. No demand without `DSP_TUNNEL_FURNACE_HEAT_GJ_PER_T`. |

### 3.4 CO2 and emissions

| Parameter ID | Value / range | Unit | Status | Source(s) | Interpretation / caveat |
|---|---:|---|---|---|---|
| `DSP_DIRECT_CO2_MODE_BASE` | fuel-derived only | policy | base accounting mode | WAG governance + lack of DSP fuel coefficient | DSP direct CO2 is zero unless a direct fuel/heat term is active. Electricity-related Scope 2 remains separate. |
| `DSP_DIRECT_CO2_T_PER_T_COIL_BASE` | 0.0 | tCO2/t coil | base placeholder | accounting policy | This is not a claim of physically zero emissions; it means no direct fuel term is active in first implementation. |
| `DSP_DIRECT_CO2_T_PER_T_COIL_IF_NG_HEAT_SENS` | derived | tCO2/t coil | derived sensitivity | fuel heat * EF_NG | Only compute if a tunnel-furnace heat term is activated. |
| `DSP_CR6_OR_NON_CO2_AIR_EMISSIONS` | deferred | qualitative | out of first energy/MILP scope | Tata DSP emissions context, if later needed | Not part of first CO2/electricity parameter set. Do not use recent emissions issues as energy-model inputs unless explicitly reopened. |

### 3.5 Flexibility and operation class

| Parameter ID | Value / range | Unit | Status | Source(s) | Interpretation / caveat |
|---|---:|---|---|---|---|
| `DSP_OPERATION_CLASS` | bounded downstream scheduling asset | policy | modelling policy | MER; Athanasiadis; Badarinath; project S2.13 governance | DSP has some downstream flexibility but is constrained by liquid-steel/continuous-casting availability and product target. |
| `DSP_MFRR_PROVIDER_BASE` | false | bool | base policy | modelling judgement | DSP is not a primary mFRR asset; no fast reserve unless a separate electrical-load model is developed. |
| `DSP_DA_FLEXIBILITY_BASE` | limited | qualitative | base policy | Athanasiadis / Badarinath precedent | Do not treat DSP as a cheap price-responsive load. It can shift only if liquid-steel routing and product fulfilment remain feasible. |
| `DSP_LIQUID_STEEL_ROUTING_BALANCE_REQUIRED` | true | bool | hard guardrail | MER / downstream governance | DSP must not consume liquid steel that is unavailable from BOF/EAF routing. |
| `DSP_OUTPUT_COUNTS_TOWARD_FINAL_PRODUCT_TARGET` | true | bool | hard guardrail | Athanasiadis; MER | DSP and HSM/WBW together form the final-product denominator. |

---

## 4. Recommended first implementation values

Recommended compact base:

```text
DSP_OUTPUT_BASIS                       = t DSP hot-rolled coil
DSP_C0_OUTPUT_ANNUAL_MT_Y              = 1.5
DSP_C1_OUTPUT_ANNUAL_MT_Y              = 1.5
DSP_C1_EAF_ROUTE_SHARE_OF_DSP          = 0.90
DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL    = 1.05
DSP_ELECTRICITY_MWH_PER_T_COIL         = 0.056
DSP_FUEL_GAS_BASE_ACTIVE               = false
DSP_DIRECT_CO2_MODE_BASE               = fuel-derived only
DSP_OPERATION_CLASS                    = bounded_downstream_scheduling_asset
```

First LP relation:

```text
DSP_liquid_steel_input[t] = DSP_output[t] * 1.05
DSP_electricity[t]        = DSP_output[t] * 0.056
DSP_internal_scrap[t]     = DSP_output[t] * 0.05
```

If material balance tightness becomes problematic, use sensitivity:

```text
DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL = 1.03 / 1.05 / 1.07
DSP_ELECTRICITY_MWH_PER_T_COIL      = 0.028 / 0.056 / 0.111
```

---

## 5. Anchors

### 5.1 Long-term / full-model anchors

| Anchor | Value | Use |
|---|---:|---|
| C0 DSP-roll output | 1.5 Mt/y | Final-product validation |
| C1 DSP-roll output | max. 1.5 Mt/y | Final-product validation |
| C1 EAF-route share in DSP | approx. 90% | Route-share validation |
| C0 total final products | 5.4 Mt rolled coils + 1.5 Mt DSP rolls = 6.9 Mt/y | Final-product denominator |
| C1 total final products | 5.5 Mt rolled coils + 1.5 Mt DSP rolls = 7.0 Mt/y | Final-product denominator |
| C1 liquid steel production | 6.8 Mt/y | Upstream steel availability check |
| C1 imported slabs to HSM | 0.6 Mt/y | HSM/DSP route-balance sanity check |

### 5.2 Small DSP checks

| Check | Use |
|---|---|
| DSP output | Main activity check |
| liquid steel input to DSP | BOF/EAF to DSP routing check |
| internal scrap/loss | yield and scrap-loop check |
| DSP electricity | full-site electricity accounting |
| C1 EAF-route share | route-origin validation |
| final product fulfilment | prevents DSP/HSM schedule from becoming pure energy arbitrage |

---

## 6. Deferred details

The following should not be included in the first implementation unless explicitly reopened:

- exact grade, width, thickness and campaign scheduling;
- exact semi-endless rolling sequence logic;
- exact tunnel-furnace fuel demand;
- exact tunnel-furnace WAG/NG carrier split;
- descaling water and water-system details;
- detailed mould-powder, chromium, dust or non-CO2 air-emission modelling;
- maintenance outages or temporary shutdowns;
- DSP as mFRR provider.

The key red flag is a DSP model that becomes a free downstream flexibility asset. The DSP can only add valid flexibility if liquid-steel routing, product fulfilment, and downstream operating bounds are respected.

---

## 7. Fully written source appendix

### S1. Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025)

**Title:** *MER Heracless – Groen Staal, Deel B: Technische beschrijving*
**Organisation / authors:** Haskoning Nederland B.V. for Tata Steel IJmuiden B.V.
**Year / date:** 15 September 2025
**URL:** https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf
**Relevant locators:**

- Section 2.2 / Table 2.1: reference liquid steel 7.2 Mt/y and Heracless 6.8 Mt/y.
- Section 3.4 / 3.5: liquid steel can be further processed in the DSP; 20% of steel from OSF goes liquid-state to DSP, 80% as slabs to WBW.
- Section 3.5.1: DSP transforms liquid steel in one continuous efficient process into hot-rolled steel rolls.
- Section 4.3: reference final products are 5.4 Mt rolled coils and 1.5 Mt DSP rolls; losses such as cutting losses are already deducted and enter the internal scrap stream.
- Section 13.7: DSP remains max. 1.5 Mt/y and process is unchanged; approx. 90% of DSP steel expected from the EAF route; WBW increases to max. 5.5 Mt/y.

**Used values:** 1.5 Mt/y DSP rolls, 20% OSF-to-DSP liquid route, 90% C1 EAF-route DSP share, unchanged DSP process, final-product anchors.
**Caveat:** Strong for public Tata topology and annual anchors; not a per-ton energy or fuel conversion table.

### S2. Tata Steel Nederland, Plants webpage

**Title:** *Plants*
**Organisation / authors:** Tata Steel Nederland
**Year / date:** webpage, accessed for this source-card preparation
**URL:** https://www.tatasteelnederland.com/en/How-we-make-steel/Plants
**Relevant locator:** Direct Sheet Plant fact-sheet entry.
**Used values:** 1.4 Mt/y steel produced per year, 70,000 rolls/y, tunnel furnace length 320 m.
**Caveat:** Public plant fact sheet; MER Heracless controls thesis C0/C1 anchors.

### S3. Kromhout et al. (2008)

**Title:** *Mould Powder Requirements for High-speed Casting*
**Authors:** J. A. Kromhout, A. Kamperman, M. Kick, S. Melzer, E. Zinngrebe, J. Trouw, Rob Boom and co-authors as listed in the publication record
**Year:** 2008
**Publication context:** technical paper with Corus IJmuiden DSP specifications
**URL:** https://www.researchgate.net/publication/267547244_Mould_Powder_Requirements_for_High-speed_Casting
**Relevant locator:** Table 1, Main specifications of Direct Sheet Plant (DSP) at Corus.
**Used values:** steel grades low carbon/HSLA, casting speed max. 6.0 m/min, mould/slab thickness 90/70 mm, strip thickness 0.7–2.5 mm, strip width 1000–1560 mm, capacity 1.3 Mt/y coils.
**Caveat:** Technical/historical Corus DSP context; not an energy model input table.

### S4. European Commission (2022)

**Title:** *Commission Implementing Decision (EU) 2022/2110 establishing the best available techniques (BAT) conclusions for the ferrous metals processing industry*
**Organisation:** European Commission
**Year / date:** 11 October 2022 / Official Journal 4 November 2022
**URL:** https://eur-lex.europa.eu/eli/dec_impl/2022/2110/oj/eng
**Relevant locator:** BAT-AEPL for hot rolling / Table 1.22.
**Used values:** hot rolling specific rolling energy range 100–400 MJ/t product = 0.0278–0.111 MWh/t.
**Caveat:** Generic hot rolling range, not DSP-specific. Used only for electricity sensitivity and order-of-magnitude support.

### S5. Worrell et al. / Lawrence Berkeley National Laboratory (2008)

**Title:** *World Best Practice Energy Intensity Values for Selected Industrial Sectors*
**Authors:** Ernst Worrell, Lynn Price, Nathan Martin, Christina Hendriks, Leticia Ozawa Meida and co-authors as listed in the report
**Organisation:** Lawrence Berkeley National Laboratory / U.S. Department of Energy context
**Year:** 2008
**URL:** https://eta-publications.lbl.gov/sites/default/files/industrial_best_practice_en.pdf
**Relevant locator:** Section 2.1.6, Rolling and Finishing.
**Used value:** final energy used for casting and rolling using thin slab casting = 0.20 GJ/t steel.
**Caveat:** Best-practice, generic thin-slab casting-and-rolling value. Use as sanity check / base electricity-equivalent candidate only; not a Tata-DSP measured value.

### S6. Athanasiadis, Ioannis (2025)

**Title:** *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel’s IJmuiden Site*
**Author:** Ioannis Athanasiadis
**Institution:** Delft University of Technology, MSc Sustainable Energy Technologies
**Year:** 2025
**Locator:** public thesis, methodology sections around PyPSA components and final steel production target; figures listing DSP and HSM modelling approach.
**Used role:** modelling precedent that final steel target is set after HSM and DSP, and that individual plants cannot instantly scale solely in response to price signals.
**Caveat:** Public thesis contains redactions and model-specific assumptions. Use as modelling precedent, not exact Tata numerical input truth.

### S7. Badarinath, Mukunda (2025)

**Title:** *Optimising Industrial Participation in the Day-Ahead Electricity Market: A Stochastic Bidding Framework with Risk Management*
**Author:** Mukunda Badarinath
**Institution:** Delft University of Technology, MSc Sustainable Energy Technology
**Year:** 2025
**Locator:** Section 2.3, Tata Steel process overview.
**Used role:** secondary precedent that DSP takes input from continuous caster / hot charging route and produces about 20% of hot rolled steel, while HSM and slab yard provide the main downstream buffering caveat.
**Caveat:** Secondary precedent; not primary source for DSP parameter values.
