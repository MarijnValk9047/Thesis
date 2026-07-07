# Direct Reduction Plant / DRP Parameters — NG Phase 1 source-card memo

## Status

This note records a compact, source-backed candidate parameter set for the Tata Steel IJmuiden-inspired Direct Reduction Plant (`DRP`) in the C1 Phase 1 hybrid route.

It is a **candidate/source-card memo**, not an executable input table and not thesis-approved truth.

Rows below must be migrated through the normal workflow before model use:

```text
source -> source card -> candidate evidence -> assumption/register row -> reviewed development input -> executable model input
```

## Scope and modelling intention

This memo is scoped to the **Phase 1 hybrid BF-BOF + NG-DRP + EAF configuration**.

The base case is explicitly:

```text
DRP reductant base = natural gas
hydrogen base = disabled / not endogenous
on-site electrolysis = out of scope
hydrogen storage = out of scope
```

Hydrogen-ready descriptions may be retained as context, but hydrogen is not a base-case input and must not silently enter the first DRP implementation.

Preferred activity basis for source-card parameters:

```text
P_DRP[t] = DRI_output[t]      # t DRI / time step
```

The DRP is a continuous, thermochemical shaft-furnace process. The first model should treat the DRP as a **slow continuous production asset**, not as a fast mFRR asset. The main flexibility mechanism is the **DRI/CDRI buffer between the continuous DRP and the batch-based EAF**.

## Source hierarchy

| Rank | Source | Main use | Reliability / caveat |
|---:|---|---|---|
| 1 | Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025), *MER Heracless - Groen Staal, Deel B: Technische beschrijving* | Tata-specific Heracless topology, NG-first phase, DRP process description, production anchors, energy intensities, CO2 capture, HDRI/CDRI flow, cold DRI silos, maintenance. | High for public Tata topology and design anchors. Does not give all optimisation coefficients such as ramp limits or exact CDRI silo capacity. |
| 2 | Project governance: *Steel Configuration Scope Freeze* and *Steel Stage Gate Validation Plan* | Locks the thesis base case to C1 Phase 1 NG-DRP-EAF, keeps hydrogen exogenous/deferred, and requires finite buffers and terminal inventory rules. | Methodological governance, not external technical evidence. |
| 3 | Athanasiadis, I. (2025), *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site* | PyPSA-style DRP Link precedent, NG-DRP candidate coefficients, operation range and ramp guardrails. | Modelling precedent only; public thesis values are not exact Tata truth. Use as development candidate where MER lacks an executable coefficient. |
| 4 | Badarinath, M. (2025), *Optimising Industrial Participation in the Day-Ahead Electricity Market* | DRP/EAF route abstraction and DRI-buffer decoupling for market response. | Secondary modelling precedent. Useful for buffer rationale; not a primary physical source. |
| 5 | Duarte / Tenova (2007), *ENERGIRON Direct Reduction Technology — Economical, Flexible, Environmentally Friendly* | Technology-specific cross-check for pellet input, NG consumption and electricity use per t DRI. | Vendor / technology source. Useful for plausibility, not Tata-specific. |
| 6 | Danieli Centro Metallics (2024), *Renewable Energy for DRI Production with ENERGIRON Technology* | Sensitivity/conflict values for NG, electricity and CO2 by-product. | Vendor presentation. Useful for sensitivity only unless independently reviewed. |

## Compact process representation

```text
pellets + natural_gas + oxygen + electricity
    -> HDRI/CDRI + captured_CO2_stream + dust/sludge/offgas diagnostics
```

Internal gas loop:

```text
process_gas_recycle + tailgas_to_process_furnace
```

The DRP does **not** create a reusable WAG carrier comparable to `BFG`, `COG` or `BOFG`. Tailgas is internal fuel for the DRP process furnace and should not enter the general WAG market or site-gas value chain as a free dispatchable product.

## Base-case policy

| Parameter ID | Most likely / base | Range / sensitivity | Unit | Status | Source ID(s) | Use / caveat |
|---|---:|---:|---|---|---|---|
| `DRP_ROUTE_SCOPE` | `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` | — | policy | base assumption | S2 | Main thesis future configuration: retained BF-BOF plus NG-DRP-EAF. |
| `DRP_TECHNOLOGY_BASE` | `HYL_Energiron` | — | technology label | base candidate | S1 | MER identifies HYL as the Energiron technology selected for the DRI plant. |
| `DRP_REDUCTANT_BASE` | `natural_gas` | — | carrier | base candidate | S1, S2 | Phase 1 / first operational phase uses natural gas. Hydrogen is later context only. |
| `DRP_HYDROGEN_ENABLED_BASE` | `false` | Optional later `C2` exogenous sensitivity only | bool | base policy | S1, S2 | Hydrogen infrastructure, storage or endogenous production must not enter the base case. |
| `DRP_H2_INPUT_T_PER_T_DRI_BASE` | 0 | deferred | t H2/t DRI | base policy | S1, S2 | Explicit zero in base case; H2 values are not carried into first executable DRP run. |
| `DRP_MFRR_ELIGIBLE_BASE` | `false` | Deferred only if separate electric process-gas heater is modelled | bool | base policy | S1, S2 | DRP is continuous thermochemical process; fast reserve should come from EAF/DRI buffer, not DRP load shedding. |

## Production and route anchors

| Parameter ID | Most likely / base | Range / sensitivity | Unit | Status | Source ID(s) | Use / caveat |
|---|---:|---:|---|---|---|---|
| `DRP_OUTPUT_BASIS` | `DRI_output` | — | t DRI | modelling choice | S1, S3 | Use DRI output as activity basis. If pellets become bus0 later, all values must be converted. |
| `DRP_C1_OUTPUT_ANNUAL_MT_Y` | 2.8 | — | Mt DRI/y | validation anchor | S1 | Heracless base DRP production anchor. Not a hard hourly constraint. |
| `DRP_C1_OPERATIONAL_FLEX_ANNUAL_MT_Y` | — | 1.9-2.8 | Mt DRI/y | validation/sensitivity | S1 | Annualised operating band. Not an hourly ramp limit. |
| `DRP_CALENDAR_AVG_DRI_T_PER_H` | 319.6 | — | t DRI/h | derived value | S1 | Derived from 2.8 Mt/y / 8760 h. Validation / scaling only. |
| `DRP_EAF_ROUTE_LS_ANNUAL_MT_Y` | 3.3 | — | Mt liquid steel/y | validation anchor | S1 | Route-coupling check against EAF liquid-steel output. |
| `DRP_HBI_IMPORT_VARIANT_MT_Y` | 0 | up to 1.1 | Mt HBI/y | sensitivity/deferred | S1 | MER operational variation: HBI can replace part of DRI production. Not base. |

## Material conversion parameters

| Parameter ID | Most likely / base | Range / sensitivity | Unit | Status | Source ID(s) | Use / caveat |
|---|---:|---:|---|---|---|---|
| `DRP_PELLET_INPUT_T_PER_T_DRI` | 1.351 | 1.35-1.40 | t pellets/t DRI | base candidate | S3, S5 | Base from Athanasiadis/project yield; vendor cross-check gives 1.35-1.40 t/t DRI. |
| `DRP_DRI_YIELD_T_PER_T_PELLETS` | 0.740 | 0.714-0.741 | t DRI/t pellets | base candidate / derived | S3, S5 | Base is Athanasiadis NG-DRP value. Vendor range is reciprocal of 1.35-1.40. |
| `DRP_PELLET_INPUT_C1_ANNUAL_MT_Y` | 3.78 | — | Mt pellets/y | derived value | S1, S3 | Derived: 2.8 Mt DRI/y * 1.351 t pellets/t DRI. Use as PeFa/import-pellet balance check. |
| `DRP_OXYGEN_INPUT_T_PER_T_PELLETS_PROJECT` | 0.100 | — | t O2/t pellets | development candidate | S3 | Athanasiadis NG-DRP table. Strongly caveated; keep as development input only until checked. |
| `DRP_OXYGEN_INPUT_T_PER_T_DRI_PROJECT` | 0.135 | — | t O2/t DRI | derived development candidate | S3 | Derived from 0.100 t/t pellets / 0.740 yield. May conflict with vendor values. |
| `DRP_OXYGEN_INPUT_NM3_PER_T_DRI_VENDOR` | 35 | — | Nm3 O2/t DRI | sensitivity / cross-check | S6 | Energiron publication value; do not mix with Athanasiadis mass basis without conversion and review. |
| `DRP_DRI_CARBON_WT_PERCENT_MER` | 5 | — | wt% C in DRI | validation / quality context | S1 | MER states Energiron/HYL reaches about 5 wt% carbon, relevant to EAF quality. Not an energy variable. |
| `DRP_DRI_CARBON_WT_PERCENT_VENDOR` | 3.5 | — | wt% C in DRI | sensitivity / conflict | S5 | Tenova high-quality DRI example. Use only as quality/context sensitivity. |

## Energy and utility parameters — natural-gas Phase 1 base

| Parameter ID | Most likely / base | Range / sensitivity | Unit | Status | Source ID(s) | Use / caveat |
|---|---:|---:|---|---|---|---|
| `DRP_NG_REDUCTION_GJ_PER_T_DRI` | 8.1 | — | GJ/t DRI | base candidate | S1 | Tata/MER Phase 1 NG value for reduction. Preferred over generic vendor value. |
| `DRP_NG_PROCESS_FURNACE_GJ_PER_T_DRI` | 1.8 | — | GJ/t DRI | base candidate | S1 | Tata/MER Phase 1 NG value for process furnace fuel. |
| `DRP_NG_TOTAL_GJ_PER_T_DRI` | 9.9 | 9.63-12.24 | GJ/t DRI | base candidate + sensitivity | S1, S5, S6 | Base is MER 8.1 + 1.8. Tenova 2.30 Gcal/t DRI = 9.63 GJ/t is close; Danieli 3400 kWh/t = 12.24 GJ/t is high sensitivity/conflict. |
| `DRP_NG_TOTAL_ANNUAL_PJ_Y` | 27.72 | — | PJ/y | derived validation | S1 | Derived: 2.8 Mt/y * 9.9 GJ/t. Use against C1 site gas-energy anchors. |
| `DRP_ELECTRICITY_GJ_PER_T_DRI` | 0.3 | — | GJ/t DRI | base candidate | S1 | Tata/MER Phase 1 electricity intensity. |
| `DRP_ELECTRICITY_MWH_PER_T_DRI` | 0.0833 | 0.060-0.080 vendor; 0.135 project-high | MWh/t DRI | base candidate + sensitivity | S1, S3, S5 | Base from MER: 0.3 GJ/t / 3.6. Vendor range is slightly lower. Athanasiadis 0.1 MWh/t pellets converts to ~0.135 MWh/t DRI and is sensitivity/conflict only. |
| `DRP_ELECTRICITY_ANNUAL_TWH_Y` | 0.233 | — | TWh/y | derived validation | S1 | Derived: 2.8 Mt/y * 0.0833 MWh/t. Excludes EAF. |
| `DRP_STEAM_SYSTEM_ENABLED` | `true` | — | bool | topology candidate | S1 | MER describes internal steam generation from process-gas heat recovery and use within the DRP. Do not add external steam price. |
| `DRP_EXTERNAL_STEAM_IMPORT_BASE` | 0 | deferred | GJ/t DRI | base policy | S1, S2 | Steam is an internal DRP system in the MER description; no external steam input is introduced in first model. |
| `DRP_TAILGAS_INTERNAL_FUEL_ENABLED` | `true` | — | bool | topology candidate | S1 | Small purge/tailgas stream is used in the process furnace, not modelled as exportable WAG. |
| `DRP_EXPORTABLE_WAG_CARRIER` | `false` | — | bool | base policy | S1, S2 | DRP tailgas/offgas is not added to the general BFG/COG/BOFG WAG network. |

## CO2 accounting and capture

| Parameter ID | Most likely / base | Range / sensitivity | Unit | Status | Source ID(s) | Use / caveat |
|---|---:|---:|---|---|---|---|
| `DRP_CO2_CAPTURE_ANNUAL_MT_Y` | 0.8 | — | Mt CO2/y | validation anchor | S1 | MER states about 0.8 Mt/y CO2 is captured from the NG-based DRP process. |
| `DRP_CO2_CAPTURE_T_PER_T_DRI` | 0.286 | — | t CO2/t DRI | derived validation | S1 | Derived: 0.8 Mt/y / 2.8 Mt DRI/y. Not additive if NG combustion/process CO2 is separately calculated. |
| `DRP_CO2_BYPRODUCT_VENDOR_T_PER_T_DRI` | 0.256 | — | t CO2/t DRI | sensitivity / cross-check | S6 | Danieli presentation value; close to MER-derived capture intensity. Use as cross-check only. |
| `DRP_UNCAPTURED_CO2_VENDOR_T_PER_T_DRI` | 0.200 | — | t CO2/t DRI | sensitivity / reporting | S6 | Danieli 100% NG fired-PGH case. Not a Tata/MER base value. |
| `DRP_CCS_TRANSPORT_AVAILABLE_BASE` | `false` / scenario flag | true if explicit CCS scenario | bool | policy/deferred | S1, S2 | MER includes variants for CO2 transport/storage and notes initial emission/transport-development issues. CCS must be scenario-tagged. |
| `DRP_CO2_ACCOUNTING_MODE` | `capture_stream_validation` | `fuel_emission_explicit` later | policy | base policy | S1, S2 | First model records CO2 capture as validation/reporting stream. Avoid double-counting with NG emission factors. |

## Process conditions and product classes

| Parameter ID | Most likely / base | Range / sensitivity | Unit | Status | Source ID(s) | Use / caveat |
|---|---:|---:|---|---|---|---|
| `DRP_PROCESS_TEMP_NG_C` | 1100 | — | degC | process condition | S1 | O2 is added for partial combustion to bring process temperature to about 1100 degC in NG phase. |
| `DRP_HDRI_DISCHARGE_TEMP_C` | 600-700 | — | degC | process condition | S1 | Hot DRI leaves reactor at 600-700 degC. |
| `DRP_TOP_GAS_EXIT_TEMP_NG_C` | 490 | — | degC | process condition | S1 | Process gas exits reactor top at about 490 degC in NG phase. |
| `DRP_TOP_GAS_RECUPERATOR_OUTLET_C` | 195 | — | degC | process condition | S1 | Top gas heat recuperator cools process gas to about 195 degC while producing internal steam. |
| `DRP_PROCESS_GAS_PRE_REACTOR_TEMP_C` | 910-950 | — | degC | process condition | S1 | Process furnace heats process gas before reactor. |
| `DRP_HDRI_DIRECT_TO_EAF_ENABLED` | `true` | — | bool | topology candidate | S1 | HDRI may be pneumatically transported under inert atmosphere via Hytemp to EAF. |
| `DRP_CDRI_PRODUCTION_ENABLED` | `true` | — | bool | topology candidate | S1 | DRP can produce cooled DRI when EAF is down or decoupling is needed. |
| `DRP_HBI_PRODUCTION_BASE` | `false` | optional import/sensitivity only | bool | base policy | S1, S2 | HBI is considered as import/variant replacement for DRI, not base endogenous production. |

## Operation, capacity and ramp guardrails

| Parameter ID | Most likely / base | Range / sensitivity | Unit | Status | Source ID(s) | Use / caveat |
|---|---:|---:|---|---|---|---|
| `DRP_AVG_CAPACITY_PELLETS_T_PER_H_DEV` | 500 | — | t pellets/h | development candidate | S3 | Athanasiadis NG-DRP table. Use as guardrail/scaling, not Tata-approved capacity. |
| `DRP_AVG_CAPACITY_DRI_T_PER_H_DEV` | 370 | — | t DRI/h | derived development candidate | S3 | Derived: 500 t pellets/h * 0.74. Similar order to MER annual average. |
| `DRP_OPERATION_RANGE_REL_OF_AVG_DEV` | 0.7-1.1 | — | fraction | development guardrail | S3 | Athanasiadis operating range. Useful to avoid free hourly swings. |
| `DRP_RAMP_LIMIT_REL_OF_AVG_PER_H_DEV` | 0.1 | — | fraction/h | development guardrail | S3 | Athanasiadis ramp up/down limit. Not public Tata control-room rule. |
| `DRP_TRANSITION_MIN_LOAD_REL` | 0.50 | — | fraction of max | validation / context | S1 | MER transition phase notes DRP and BF lower bound around 50% max capacity. Use as sanity check, not base hourly envelope. |
| `DRP_ANNUAL_MAINTENANCE_DAYS` | 21 | — | days/y | availability anchor | S1 | Annual DRP shutdown. Useful for availability sensitivity, not first 24h smoke. |
| `DRP_REPEATING_MAINTENANCE_DAYS_PER_MONTH` | 1 | — | days/month | availability anchor | S1 | MER expects about one day per month for DRP maintenance. |
| `DRP_UNPLANNED_SHUTDOWN_AS_MFRR` | `false` | — | bool | base policy | S1, S2 | Unplanned shutdown requires controlled depressurising, flaring/process handling and is not reserve-like operation. |

## Buffer and inventory parameters

| Parameter ID | Most likely / base | Range / sensitivity | Unit | Status | Source ID(s) | Use / caveat |
|---|---:|---:|---|---|---|---|
| `DRP_PELLET_DAYSILO_ENABLED` | `true` | — | bool | topology candidate | S1 | MER states day silos for pellet working stock at the DRI plant. |
| `DRP_PELLET_DAYSILO_CAPACITY_T` | deferred | — | t pellets | deferred detail | S1 | Public MER confirms existence, not capacity. Do not invent. |
| `DRP_CDRI_SILO_ENABLED` | `true` | — | bool | topology candidate | S1 | MER states cold DRI silos are provided. |
| `DRP_CDRI_SILO_CAPACITY_PUBLIC_T` | unknown | — | t DRI | source gap | S1 | Public MER confirms cold DRI silo existence, not numerical capacity. |
| `DRI_BUFFER_CAPACITY_DAYS_BASE` | 2.0 | 1.0-3.0 sensitivity | days of DRP output | base modelling candidate | S4, S2 | Two days follows Badarinath/Athanasiadis-style DRP-EAF decoupling precedent. Sensitivity allowed by C1S governance. |
| `DRI_BUFFER_CAPACITY_T_BASE` | 15350 | 7675-23025 sensitivity | t DRI | derived base candidate | S1, S4 | Derived from 2 days * 2.8 Mt/y / 365. Not a public Tata silo capacity. |
| `DRI_BUFFER_CAPACITY_HOURS_BASE` | 48 | 24-72 sensitivity | h | derived base candidate | S4, S2 | Same capacity expressed as hours. Useful for hourly model. |
| `DRI_BUFFER_MODE_BASE` | `CDRI_store_with_HDRI_direct_transfer` | — | policy | base modelling candidate | S1, S4 | HDRI can go directly to EAF; CDRI can be cooled and stored in silos. |
| `DRI_BUFFER_INITIAL_SHARE` | 0.50 | sensitivity 0.25-0.75 | fraction of capacity | modelling policy | S2 | Use mid-level initial inventory to avoid free buffer energy. Must be reported. |
| `DRI_BUFFER_TERMINAL_RULE` | `end_equals_initial` | `end_ge_initial` sensitivity only | policy | modelling policy | S2 | S4.4 regression gate already uses DRI terminal equality; avoids end-horizon buffer depletion. |
| `DRI_BUFFER_SURPLUS_ALLOWED_DIAGNOSTIC` | `true` | — | bool | diagnostic policy | S2 | Surplus/gap must be reported, not hidden as free slack. |
| `DRI_BUFFER_GAP_TOLERANCE_REL` | 0.01 | — | fraction | healthcheck | S2 | Practical healthcheck threshold. Not a physical source value. |
| `DRI_BUFFER_GAP_TOLERANCE_T` | 500 | — | t DRI | healthcheck | S1, S2 | Roughly compatible with 0.1 Mt/y-rounded public anchors; use for warnings, not feasibility. |

## Recommended first implementation values

For the first deterministic C1 NG-DRP implementation:

```text
DRP_OUTPUT_BASIS                     = t DRI
DRP_HYDROGEN_ENABLED_BASE            = false
DRP_PELLET_INPUT_T_PER_T_DRI          = 1.351
DRP_NG_REDUCTION_GJ_PER_T_DRI         = 8.1
DRP_NG_PROCESS_FURNACE_GJ_PER_T_DRI   = 1.8
DRP_NG_TOTAL_GJ_PER_T_DRI             = 9.9
DRP_ELECTRICITY_MWH_PER_T_DRI         = 0.0833
DRP_CO2_CAPTURE_T_PER_T_DRI           = 0.286  # reporting/validation stream
DRP_CDRI_SILO_ENABLED                 = true
DRI_BUFFER_CAPACITY_DAYS_BASE         = 2.0
DRI_BUFFER_CAPACITY_T_BASE            = 15350
DRI_BUFFER_INITIAL_SHARE              = 0.50
DRI_BUFFER_TERMINAL_RULE              = end_equals_initial
DRP_MFRR_ELIGIBLE_BASE                = false
```

## Suggested simple equations

```text
DRI_output[t] = P_DRP[t]

pellets_to_DRP[t] = DRI_output[t] * DRP_PELLET_INPUT_T_PER_T_DRI
ng_reduction[t]   = DRI_output[t] * DRP_NG_REDUCTION_GJ_PER_T_DRI
ng_furnace[t]     = DRI_output[t] * DRP_NG_PROCESS_FURNACE_GJ_PER_T_DRI
electricity[t]    = DRI_output[t] * DRP_ELECTRICITY_MWH_PER_T_DRI
co2_capture[t]    = DRI_output[t] * DRP_CO2_CAPTURE_T_PER_T_DRI
```

DRI balance:

```text
DRI_inventory[t] = DRI_inventory[t-1]
                 + CDRI_production[t]
                 - CDRI_to_EAF[t]
                 - DRI_gap[t]
                 + DRI_surplus[t]

HDRI_direct_to_EAF[t] + CDRI_production[t] = DRI_output[t]
```

Terminal rule:

```text
DRI_inventory[end] = DRI_inventory[start]
```

## Small DRP checks

| Check | Expected value / source | Purpose |
|---|---:|---|
| DRI output | 2.8 Mt/y | Main activity validation. |
| Pellet input | ~3.78 Mt/y derived | Pellet balance with PeFa/imported pellets. |
| NG total | ~27.72 PJ/y derived | Gas-cost and energy-anchor reconciliation. |
| Electricity | ~0.233 TWh/y derived | DRP electricity accounting; keep separate from EAF electricity. |
| Captured CO2 stream | 0.8 Mt/y | CO2 reporting / capture validation. |
| DRI buffer capacity | ~15.35 kt base | Buffer no-free-battery check. |
| CDRI silo existence | true | Structural buffer check. |
| Terminal inventory | end=start | Prevents artificial end-horizon depletion. |

## Long-term / full-model anchors

| Anchor | Value | Use |
|---|---:|---|
| C1 total liquid steel | 6.8 Mt/y | Site production validation. |
| C1 DRP output | 2.8 Mt DRI/y | DRP activity validation. |
| C1 EAF liquid steel | 3.3 Mt/y | DRP -> EAF route validation. |
| C1 EAF scrap | 0.9-1.8 Mt/y | DRI displacement by scrap sensitivity. |
| C1 CO2 capture from DRP | 0.8 Mt/y | CO2 stream validation. |
| C1 imported pellets base | 0.2 Mt/y | Pellet balance. |
| C1 imported pellets variant | up to 2.5 Mt/y | PeFa/DRP burden sensitivity. |
| HBI import variant | up to 1.1 Mt/y | DRI replacement sensitivity. |
| C1 site additional grid import | 10 PJ/y | Full-site electricity plausibility, not DRP-only. |

## Explicitly deferred details

The following are **not** first-base inputs:

- Hydrogen consumption or hydrogen blending.
- On-site electrolysis, hydrogen storage or hydrogen infrastructure optimisation.
- Endogenous HBI production.
- Detailed process-gas composition and dynamic reactor chemistry.
- Detailed CO2 compression/dehydration energy unless CCS scenario is explicitly enabled.
- E-PGH/process-gas-heater electrification as a flexible electrical asset.
- DRP participation in mFRR.
- Exact CDRI silo capacity, because public MER confirms the silos but not capacity.

## Main caveats

1. **No hydrogen in base.** The base configuration is NG-DRP-EAF. Hydrogen belongs only to later explicit sensitivity/context.
2. **DRP is not EAF.** DRP electricity is auxiliary/continuous and should not be treated as fast flexible arc-power.
3. **DRI buffer is not a free battery.** Capacity, initial level and terminal rule must be explicit before any DA or mFRR claims.
4. **Do not double-count CO2.** If NG emissions are calculated from fuel consumption, `0.8 Mt/y` CO2 capture must be handled as a capture stream/validation anchor, not as an additional independent emission.
5. **Tailgas is not WAG.** Tailgas is internal process-furnace fuel, not a new market-valued site-gas carrier.

## Source appendix

### S1 — Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025)

**Title:** *MER Heracless - Groen Staal, Deel B: Technische beschrijving*
**Organisation:** Haskoning Nederland B.V. / Royal HaskoningDHV for Tata Steel IJmuiden B.V.
**Date:** 15 September 2025.
**URL:** https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf
**Main locators used:**

- Chapter 2.2 / Tables 2.1-2.2: Heracless phases; operation with natural gas first, later hydrogen mix.
- Chapter 5.1-5.2.1: Heracless replaces BF7/KGF2 route with DRI-fabriek and EAF; DRI process with NG/H2 context.
- Chapter 5.4 / Tables 5.1-5.2: DRP output 2.8 Mt/y, operational flexibility 1.9-2.8 Mt/y, EAF output 3.3 Mt/y, route volumes and scrap ranges.
- Chapter 5.5: materials and energy anchors; C1 gas, electricity and CO2 context.
- Chapter 6.2.3: selected HYL/Energiron technology; HYL equals the Energiron technology; HYL/Energiron advantages over MIDREX and standard CO2 removal.
- Chapter 6.3.5: CO2 transport and storage variants; first-period transport/storage caveat.
- Chapter 10.1-10.6: DRP process, NG phase, HDRI/CDRI, process-gas loop, MDEA CO2 removal, tailgas, steam system, CDRI production, energy values 8.1 GJ/t DRI reduction NG, 1.8 GJ/t DRI furnace NG, 0.3 GJ/t DRI electricity.
- Chapter 12.2-12.3: pellet day silos, CDRI silos, pellet transport to DRI and EAF auxiliary transport.
- Chapter 15.3: DRP annual maintenance 21 days and recurring monthly maintenance.

### S2 — Project governance / configuration scope freeze and stage-gate plan

**Title:** *Steel Configuration Scope Freeze* and *Steel Stage Gate Validation Plan*
**Organisation:** Thesis repository governance documents.
**Year:** 2026.
**URL/path:** `docs/optimisation/steel/STEEL_CONFIGURATION_SCOPE_FREEZE.md`; `docs/optimisation/steel/STEEL_STAGE_GATE_VALIDATION_PLAN.md`
**Main locators used:**

- C1 is the Phase 1 hybrid BF-BOF plus NG-DRP plus EAF configuration.
- Hydrogen is not endogenous in the base steel model; hydrogen appears only as optional later exogenous sensitivity.
- Buffers require finite capacity and terminal rules.
- S4.4c current C1 physical regression uses DRI inventory balance and terminal equality.

### S3 — Athanasiadis, I. (2025)

**Title:** *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site*
**Author:** Ioannis Athanasiadis.
**Institution:** Delft University of Technology, MSc Sustainable Energy Technologies.
**Year:** 2025.
**Repository URL:** https://resolver.tudelft.nl/uuid:7a0b891b-ceb8-4ceb-9d80-d0a5566dc618
**Main locators used:**

- Chapter 3.5.4 / Figure 47 and Table 2: NG-DRP modelling approach and parameters: average capacity 500 t pellets/h, pellets-to-DRI efficiency 0.74, electricity 0.1 MWh/t pellets, natural gas 195 m3/t pellets, CO2 0.5 t/t pellets, oxygen 0.1 t/t pellets, operating range 0.7-1.1 average capacity, ramp limits 0.1 average capacity per hour.
- Used only as a modelling precedent and development candidate source, not as exact Tata truth.

### S4 — Badarinath, M. (2025)

**Title:** *Optimising Industrial Participation in the Day-Ahead Electricity Market: A Stochastic Bidding Framework with Risk Management*
**Author:** Mukunda Badarinath.
**Institution:** Delft University of Technology, MSc Sustainable Energy Technology.
**Year:** 2025.
**Local source:** `Master_Thesis_Mukunda_Badarinath.pdf` in project files.
**Main locators used:**

- Section 2.3.4: future DRP-EAF route, NG-based DRP in Phase 1, DRI buffer decoupling continuous DRP from batch EAF, two days of DRP output as DRI buffer.
- Section 5.2.3 and results discussion: DRI storage as key decoupling mechanism enabling EAF price response.
- Used as secondary modelling precedent, not as primary physical source.

### S5 — Duarte / Tenova (2007)

**Title:** *ENERGIRON Direct Reduction Technology — Economical, Flexible, Environmentally Friendly*
**Author/organisation:** P. Duarte / HYL Technologies / Tenova.
**Year:** 2007.
**URL:** https://tenova.com/sites/default/files/2021-09/2007-ENERGIRON-Direct-Reduction-Technology-Economical-Flexible-Environmentally-Friendly.pdf
**Exact values used:**

- Natural gas thermal energy: 2.30 Gcal/t DRI = 9.63 GJ/t DRI.
- Electricity: 60-80 kWh/t DRI.
- Iron ore consumption: 1.35-1.40 t/t DRI.
- Example DRI: 94% metallisation, 3.5% carbon, discharged at 700 degC.

### S6 — Danieli Centro Metallics (2024)

**Title:** *Renewable Energy for DRI Production with ENERGIRON Technology*
**Author/organisation:** Marco Lapasin, Danieli Centro Metallics.
**Year:** 2024.
**URL:** https://2024.aisusteel.org/wp-content/uploads/2024/10/Danieli-Renewable-Energy-For-DRI-Production-With-ENERGIRON-Technology.pdf
**Values used as sensitivity/cross-check:**

- NG consumption high sensitivity: 3400 kWh/t DRI = 12.24 GJ/t DRI.
- Core electricity range: 60-75 kWh/t DRI.
- Selective CO2 by-product/storage/sale potential around 256 kg CO2/t DRI.
- Uncaptured CO2 sensitivity around 200 kg CO2/t DRI for 100% NG fired-PGH case.
- Electric process gas heater / E-PGH capacity values are deferred and not base model inputs.
