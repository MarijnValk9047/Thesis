# Boilers, STEG11 and TG2 Steam-Circuit Parameters

## Purpose

Compact but explicit source-card memo for the Tata Steel IJmuiden-inspired boiler and steam-circuit layer.

This memo covers:

- boiler group `K15_K16` in Centrale 1;
- boiler group `K23_K24` in Centrale 2;
- separate boiler `K41` in Centrale 2 / Centrale 4 terminology in gas-network sources;
- `STEG11` as Tata ENB gas-turbine plus heat-recovery steam generator (`GT11 + AK11`);
- `TG2` as steam-only turbo-generator / pressure-reduction route.

The aim is to represent **functionality and physical presence** of the steam/WAG system without building a full utility digital twin. The layer should close steam demand and useful WAG/NG allocation, not create an uncontrolled electricity-arbitrage asset.

This memo is **not** an approved executable input table. It records source-backed candidate values, modelling decisions, PyPSA-style implementation guidance, caveats, and validation anchors.

---

## First implementation decision

### Included

- Separate pressure-level buses for at least:
  - `steam_72bar`
  - `steam_45bar`
  - `steam_15bar`
- Optional deferred low-pressure bus:
  - `steam_0_5bar` or `steam_low`
- Three boiler fuel/steam blocks:
  - `BOILER_C1_K15K16`: `BFG + COG + NG -> steam_72bar`
  - `BOILER_C2_K23K24`: `BFG + COG + NG -> steam_45bar`
  - `BOILER_C2_K41`: `BFG + NG -> steam_45bar`
- `STEG11_CHP`: `BFG + NG_backup -> electricity + steam_72bar`
- `TG2_STEAM_TURBINE`: `steam_72bar -> electricity + steam_15bar` with low-pressure output deferred or diagnostic.
- Steam reduction/bypass routes:
  - `steam_72bar -> steam_45bar`
  - `steam_72bar -> steam_15bar`
  - `steam_45bar -> steam_15bar`
- Steam surplus or blow-off as explicit diagnostic sink, not hidden slack.

### Excluded or deferred

- Full turbine thermodynamics and enthalpy-based steam modelling.
- Exact boiler efficiencies beyond source-table-derived capacity ratios.
- Unit commitment, ramp limits, minimum stable loads and start-up logic for boilers/STEG/TG2.
- Full island-operation logic or black-start modelling.
- mFRR participation from boilers, STEG11 or TG2.
- Vattenfall generators (`IJM01`, `VN24`, `VN25`) except as separate later interface layer.
- Exact contract logic, internal transfer prices, WAG export revenue and electricity-profit claims.

---

## Source hierarchy

| Source ID | Source | Main use | Status |
|---|---|---|---|
| `S1_MER_ENERGIE_CO2_2025` | Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025). *Detailstudie Energie en CO2-balans, MER Heracless - Groen Staal*. Reference `BI3580-IB-RP`, Definitief, 15 September 2025. URL: https://pas.commissiemer.nl/files/nl/3730/01-Energie.pdf | Tata-specific steam system, Centrale 1/2 roles, `GT11 + AK11`, `TG2`, boiler capacities, steam pressure levels, reducer/bypass logic. Key locators: Appendix A1, pages 92-100; Table 0.1 on page 94/99 in parsed PDF. | Highest source for steam-system topology and capacities. |
| `S2_QRA_REFERENTIE_2025` | Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025). *Detailstudie Externe Veiligheid - QRA actuele bedrijfssituatie, MER Heracless*. Reference `BI3580-IB-RP`, Definitief, 15 September 2025. URL: https://pas.commissiemer.nl/files/nl/3730/11-a-Veiligheid-referentie.pdf | Current gas-network consumers and fuel eligibility. BFG consumers include `STEG11 (AK11)`, K15, K16, K23, K24 and K41. COG consumers include K15, K16, K23 and K24. Also confirms natural-gas distribution network on Tata site and ENB/GOS supply context. Key locators: §6.3, pages 33-35. | Strong source for BFG/COG topology; NG eligibility remains more general. |
| `S3_QRA_HERACLESS_2025` | Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025). *Detailstudie Externe Veiligheid - QRA Heracless, MER Heracless*. Reference `BI3580-IB-RP`, Definitief, 15 September 2025. URL: https://pas.commissiemer.nl/files/nl/3730/11-b-Veiligheid-Heracless.pdf | Heracless-era BFG consumers: wind heater HO6, Centrale 1 `STEG11 (AK11)`, K15/K16 and Centrale 2 K41/K23/K24. Key locator: §6.4.3.1, page 40. | Strong C1 topology check. |
| `S4_ATHANASIADIS_2025` | Athanasiadis, I. (2025). *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel’s IJmuiden Site*. TU Delft MSc thesis. | Modelling precedent for WAG buses, boiler-controller Links, steam demand, simplified gas network and PyPSA-style representation. Key locator: Figure 32 and section on WAG consumption by boilers. | Modelling precedent only; not exact Tata-public numerical source. |
| `S5_PROJECT_GOVERNANCE` | Project governance / steel source-card policy documents. | Enforces no direct WAG market valuation, no fake buffer batteries, no workbook-only executable use, and source-to-input separation. | Governance, not external evidence. |

---

## Physical interpretation

The boiler and steam circuit is not a production plant like BF/BOF/EAF. It is a **utility conversion layer**:

```text
WAGs / NG -> boiler or CHP -> steam buses (+ electricity for STEG11/TG2)
steam buses -> process steam loads / pressure reducers / diagnostic blow-off
```

The economic role is also limited:

- WAG value is realised only through useful steam generation or CHP substitution of NG/electricity.
- NG enters as an explicit external fuel where allowed.
- WAGs must not receive a direct DA electricity-market price.
- TG2/STEG11 must not be allowed to dominate results via unconstrained electricity arbitrage.

---

## Recommended PyPSA-style topology

### Buses

| Bus ID | Carrier | Unit convention | Role |
|---|---|---|---|
| `bfg_bus` | BFG | MWh_LHV/h or GJ/h | Source from blast furnaces / BFG holder. |
| `cog_bus` | COG | MWh_LHV/h or GJ/h | Source from coking plants / COG holder. |
| `ng_bus` | NG | MWh_LHV/h or GJ/h | External natural-gas import. |
| `boiler_c1_k15k16_fuel_heat_bus` | mixed fuel heat | MWh_LHV/h or GJ/h | Controller bus for K15/K16. |
| `boiler_c2_k23k24_fuel_heat_bus` | mixed fuel heat | MWh_LHV/h or GJ/h | Controller bus for K23/K24. |
| `boiler_c2_k41_fuel_heat_bus` | mixed fuel heat | MWh_LHV/h or GJ/h | Controller bus for K41. |
| `steg11_fuel_heat_bus` | fuel heat | MWh_LHV/h or GJ/h | Controller bus for STEG11. |
| `steam_72bar` | steam | t steam/h in first implementation | High-pressure Centrale 1 steam. |
| `steam_45bar` | steam | t steam/h in first implementation | Centrale 2 steam / wind-machine and process steam level. |
| `steam_15bar` | steam | t steam/h in first implementation | Process/heating steam level. |
| `steam_low` | steam | t steam/h | Optional aggregation of 0.5 bar steam; deferred if not needed. |
| `electricity_internal` | electricity | MWh/h | Internal electricity accounting bus. |
| `steam_spill_diagnostic` | diagnostic sink | t steam/h | Explicit blow-off/surplus reporting. |

### Controller Links

Use simple controller Links from gas buses into fuel-heat buses. These Links do not create value; they only allocate available gas to eligible consumers.

```text
bfg_bus -> boiler_c1_k15k16_fuel_heat_bus
cog_bus -> boiler_c1_k15k16_fuel_heat_bus
ng_bus  -> boiler_c1_k15k16_fuel_heat_bus

bfg_bus -> boiler_c2_k23k24_fuel_heat_bus
cog_bus -> boiler_c2_k23k24_fuel_heat_bus
ng_bus  -> boiler_c2_k23k24_fuel_heat_bus

bfg_bus -> boiler_c2_k41_fuel_heat_bus
ng_bus  -> boiler_c2_k41_fuel_heat_bus

bfg_bus -> steg11_fuel_heat_bus
ng_bus  -> steg11_fuel_heat_bus   # backup / caveated
```

`COG -> K41` is excluded in the first implementation. `COG -> STEG11` is deferred/excluded unless a later source explicitly supports it.

### Conversion Links

```text
boiler_c1_k15k16_fuel_heat_bus -> steam_72bar
boiler_c2_k23k24_fuel_heat_bus -> steam_45bar
boiler_c2_k41_fuel_heat_bus    -> steam_45bar

steg11_fuel_heat_bus -> electricity_internal + steam_72bar
steam_72bar          -> electricity_internal + steam_15bar   # TG2

steam_72bar -> steam_45bar       # pressure reduction / backup
steam_72bar -> steam_15bar       # pressure reduction / bypass
steam_45bar -> steam_15bar       # pressure reduction / backup
steam_*     -> steam_spill_diagnostic   # explicit surplus, penalty/reporting only
```

### Why use steam in `t/h` first?

The public source gives steam capacities in `t/h`, pressure and temperature. It does not give enough public thermodynamic detail to build a rigorous enthalpy-based steam model. A first implementation can therefore track steam as a mass carrier and use the source-table ratios between MWth input and t/h steam output as effective conversion coefficients.

This is not a detailed boiler-efficiency model. It is a controlled accounting abstraction.

---

## Core parameter table

### Boiler capacities and fuel eligibility

| Parameter ID | Value | Unit | Status | Source link(s) | Model use / caveat |
|---|---:|---|---|---|---|
| `BOILER_C1_K15_STEAM_MAX_T_H` | 110 | t steam/h | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Individual K15 steam capacity. |
| `BOILER_C1_K16_STEAM_MAX_T_H` | 110 | t steam/h | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Individual K16 steam capacity. |
| `BOILER_C1_K15_MWTH` | 96.4 | MWth | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Max thermal input / boiler capacity representation. |
| `BOILER_C1_K16_MWTH` | 96.4 | MWth | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Max thermal input / boiler capacity representation. |
| `BOILER_C1_K15K16_STEAM_MAX_T_H` | 220 | t steam/h | derived candidate | K15 + K16 from `S1_MER_ENERGIE_CO2_2025` | Aggregate first implementation group. |
| `BOILER_C1_K15K16_MWTH` | 192.8 | MWth | derived candidate | K15 + K16 from `S1_MER_ENERGIE_CO2_2025` | Aggregate thermal capacity. |
| `BOILER_C1_K15K16_FUEL_MWH_PER_T_STEAM` | 0.876 | MWhth/t steam | derived modelling coefficient | 192.8 MWth / 220 t/h | Effective source-table conversion ratio; not an explicit boiler efficiency. |
| `BOILER_C1_STEAM_PRESSURE_BARG` | 72 | bar(g) | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Connect to `steam_72bar`. |
| `BOILER_C1_STEAM_TEMP_C` | 505 | °C | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Reporting / source-card context. |
| `BOILER_C1_K15K16_BFG_ALLOWED` | true | bool | source-backed base | `S2_QRA_REFERENTIE_2025`, `S3_QRA_HERACLESS_2025` | BFG explicitly feeds K15/K16. |
| `BOILER_C1_K15K16_COG_ALLOWED` | true | bool | source-backed base | `S2_QRA_REFERENTIE_2025` | COG consumers include Ketel 15/16. |
| `BOILER_C1_K15K16_NG_ALLOWED` | true | bool | modelling base with caveat | `S2_QRA_REFERENTIE_2025`; user policy | QRA confirms site NG network/ENB context. Per-boiler NG firing is less specific than BFG/COG; use as external backup/fuel option with caveat. |
| `BOILER_C2_K23_STEAM_MAX_T_H` | 110 | t steam/h | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Individual K23 steam capacity. |
| `BOILER_C2_K24_STEAM_MAX_T_H` | 110 | t steam/h | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Individual K24 steam capacity. |
| `BOILER_C2_K23_MWTH` | 96.2 | MWth | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Max thermal capacity. |
| `BOILER_C2_K24_MWTH` | 93.1 | MWth | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Max thermal capacity. |
| `BOILER_C2_K23K24_STEAM_MAX_T_H` | 220 | t steam/h | derived candidate | K23 + K24 from `S1_MER_ENERGIE_CO2_2025` | Separate from K41 to avoid false common eligibility. |
| `BOILER_C2_K23K24_MWTH` | 189.3 | MWth | derived candidate | K23 + K24 from `S1_MER_ENERGIE_CO2_2025` | Aggregate thermal capacity. |
| `BOILER_C2_K23K24_FUEL_MWH_PER_T_STEAM` | 0.861 | MWhth/t steam | derived modelling coefficient | 189.3 MWth / 220 t/h | Effective source-table conversion ratio. |
| `BOILER_C2_K23K24_STEAM_PRESSURE_BARG` | 45 | bar(g) | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Connect to `steam_45bar`. |
| `BOILER_C2_K23K24_STEAM_TEMP_C` | 465 | °C | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Reporting / source-card context. |
| `BOILER_C2_K23K24_BFG_ALLOWED` | true | bool | source-backed base | `S2_QRA_REFERENTIE_2025`, `S3_QRA_HERACLESS_2025` | BFG explicitly feeds K23/K24. |
| `BOILER_C2_K23K24_COG_ALLOWED` | true | bool | source-backed base | `S2_QRA_REFERENTIE_2025` | COG consumers include Ketel 23/24. |
| `BOILER_C2_K23K24_NG_ALLOWED` | true | bool | modelling base with caveat | `S2_QRA_REFERENTIE_2025`; user policy | Include NG as external fuel option; per-boiler NG source is less direct than BFG/COG. |
| `BOILER_C2_K41_STEAM_MAX_T_H` | 80 | t steam/h | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | K41 steam capacity; kept separate. |
| `BOILER_C2_K41_MWTH` | 56 | MWth | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | K41 thermal capacity. |
| `BOILER_C2_K41_FUEL_MWH_PER_T_STEAM` | 0.700 | MWhth/t steam | derived modelling coefficient | 56 MWth / 80 t/h | Effective source-table conversion ratio; K41 is not forced to share K23/K24 ratio. |
| `BOILER_C2_K41_STEAM_PRESSURE_BARG` | 45 | bar(g) | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Connect to `steam_45bar`. |
| `BOILER_C2_K41_STEAM_TEMP_C` | 465 | °C | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Reporting / source-card context. |
| `BOILER_C2_K41_BFG_ALLOWED` | true | bool | source-backed base | `S2_QRA_REFERENTIE_2025`, `S3_QRA_HERACLESS_2025` | K41 explicitly listed as BFG consumer. |
| `BOILER_C2_K41_COG_ALLOWED` | false | bool | base exclusion | `S2_QRA_REFERENTIE_2025` | COG consumer list mentions K15/16/23/24 but not K41. |
| `BOILER_C2_K41_NG_ALLOWED` | true | bool | modelling base with caveat | `S2_QRA_REFERENTIE_2025`; user policy | Include NG to preserve feasible steam back-up; source is gas-network/ENB context, not a per-burner certificate. |
| `BOILER_EXPLICIT_EFFICIENCY` | deferred | fraction | deferred | no strong public source | Do not invent independent efficiency. Use source-table-derived fuel/steam ratios in first model. |
| `BOILER_MIN_LOAD` | deferred | fraction | deferred | no strong public source | Avoid false operational precision. |
| `BOILER_RAMP_LIMIT` | deferred | t/h/h or MW/h | deferred | no strong public source | Not required for first deterministic accounting. |
| `BOILER_MFRR_ENABLED_BASE` | false | bool | policy | `S5_PROJECT_GOVERNANCE` | Steam circuit is not a first-stage reserve asset. |

### STEG11 parameters

| Parameter ID | Value | Unit | Status | Source link(s) | Model use / caveat |
|---|---:|---|---|---|---|
| `STEG11_ENABLED` | true | bool | base topology | `S1_MER_ENERGIE_CO2_2025` Appendix A1 | Tata ENB Centrale 1 includes a STEG installation. |
| `STEG11_TYPE` | `GT11 + AK11` | text | base topology | `S1_MER_ENERGIE_CO2_2025` Appendix A1 | Gas turbine with generator plus exhaust-gas boiler / HRSG. |
| `STEG11_THERMAL_INPUT_MAX_MWTH` | 85 | MWth | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Fuel-heat input cap for first CHP abstraction. |
| `STEG11_ELECTRICITY_MAX_MWE` | 13.1 | MWe | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Electricity output cap. |
| `STEG11_STEAM_OUTPUT_MAX_T_H` | 80 | t steam/h | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | 72 bar steam output via AK11. |
| `STEG11_STEAM_PRESSURE_BARG` | 72 | bar(g) | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Connect to `steam_72bar`. |
| `STEG11_STEAM_TEMP_C` | 505 | °C | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Reporting / source-card context. |
| `STEG11_ELECTRIC_EFF_PER_FUEL_MWH` | 0.154 | MWh_el/MWhth | derived modelling coefficient | 13.1 MWe / 85 MWth | Effective source-table ratio, not detailed gas turbine efficiency. |
| `STEG11_STEAM_T_PER_MWH_FUEL` | 0.941 | t steam/MWhth | derived modelling coefficient | 80 t/h / 85 MWth | Effective source-table ratio. |
| `STEG11_FUEL_MWH_PER_T_STEAM` | 1.063 | MWhth/t steam | derived modelling coefficient | 85 MWth / 80 t/h | Useful if dispatch is steam-output-led. |
| `STEG11_ELECTRICITY_MWH_PER_T_STEAM` | 0.164 | MWh_el/t steam | derived modelling coefficient | 13.1 MWe / 80 t/h | Use only if STEG11 dispatch is steam-output-led. |
| `STEG11_BFG_ALLOWED` | true | bool | source-backed base | `S2_QRA_REFERENTIE_2025`, `S3_QRA_HERACLESS_2025` | STEG11/AK11 explicitly listed as BFG consumer. |
| `STEG11_NG_BACKUP_ALLOWED` | true | bool | modelling base with caveat | `S2_QRA_REFERENTIE_2025`; user policy | NG is included as back-up/external fuel option. Per-STEG NG firing is less directly source-backed than BFG. |
| `STEG11_COG_ALLOWED` | false/deferred | bool | base exclusion | `S2_QRA_REFERENTIE_2025` | COG source list mentions boilers and IJM01 start-up, not STEG11. |
| `STEG11_MFRR_ENABLED_BASE` | false | bool | policy | `S5_PROJECT_GOVERNANCE` | Not a reserve asset in first steam/WAG accounting layer. |
| `STEG11_MARKET_ELECTRICITY_REVENUE_ACTIVE` | false | bool | policy | `S5_PROJECT_GOVERNANCE` | Do not let STEG11 create uncontrolled DA revenue in this source-card layer. Electricity is accounting/offset unless later economic policy activates it. |

### TG2 parameters

| Parameter ID | Value | Unit | Status | Source link(s) | Model use / caveat |
|---|---:|---|---|---|---|
| `TG2_ENABLED` | true | bool | base topology | `S1_MER_ENERGIE_CO2_2025` Appendix A1 | Centrale 1 has turbo-generator TG2. |
| `TG2_INPUT_CARRIER` | `steam_72bar` | carrier | base topology | `S1_MER_ENERGIE_CO2_2025` Appendix A1 | TG2 is steam-only. No BFG/COG/NG input. |
| `TG2_ELECTRICITY_MAX_MWE` | 14.5 | MWe | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Max electricity output. |
| `TG2_STEAM_FLOW_MAX_T_H` | 105 | t steam/h | base candidate with caveat | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Use as approximate max steam throughput to 15 bar route. Exact extraction/split requires detailed steam model. |
| `TG2_OUTPUT_STEAM_15BAR_T_H` | 105 | t steam/h | base candidate with caveat | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Main simplified output to `steam_15bar`. |
| `TG2_OUTPUT_STEAM_LOW_T_H` | 20 | t steam/h | deferred / optional | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Low-pressure 0.5 bar stream. Can be omitted or aggregated into `steam_low` first. |
| `TG2_OUTPUT_STEAM_15BAR_PRESSURE_BARG` | 15 | bar(g) | base candidate | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Connect to `steam_15bar`. |
| `TG2_OUTPUT_STEAM_15BAR_TEMP_C` | 350 | °C | source context | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Reporting/source-card context. |
| `TG2_OUTPUT_STEAM_LOW_PRESSURE_BARG` | 0.5 | bar(g) | deferred / optional | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Optional low-pressure bus. |
| `TG2_OUTPUT_STEAM_LOW_TEMP_C` | 175 | °C | deferred / optional | `S1_MER_ENERGIE_CO2_2025`, Table 0.1 | Optional low-pressure bus. |
| `TG2_ELECTRICITY_MWH_PER_T_STEAM_MAIN` | 0.138 | MWh_el/t steam | derived modelling coefficient | 14.5 MWe / 105 t/h | First simplified TG2 conversion. Do not over-interpret thermodynamically. |
| `TG2_BYPASS_REDUCTION_AVAILABLE` | true | bool | source-backed topology | `S1_MER_ENERGIE_CO2_2025` Appendix A1 | Parallel steam reducers can feed 15 bar steam if TG2 is stopped. |
| `TG2_MFRR_ENABLED_BASE` | false | bool | policy | `S5_PROJECT_GOVERNANCE` | TG2 is not a base reserve asset. |
| `TG2_MARKET_ELECTRICITY_REVENUE_ACTIVE` | false | bool | policy | `S5_PROJECT_GOVERNANCE` | Electricity output should be accounting/offset until economic policy is explicitly activated. |

### Steam pressure-reduction and diagnostic parameters

| Parameter ID | Value | Unit | Status | Source link(s) | Model use / caveat |
|---|---:|---|---|---|---|
| `STEAM_72_TO_45_REDUCTION_ALLOWED` | true | bool | source-backed topology | `S1_MER_ENERGIE_CO2_2025` Appendix A1 | 72 bar steam from Centrale 1 can supplement 45 bar steam net of Centrale 2. |
| `STEAM_45_TO_15_REDUCTION_ALLOWED` | true | bool | source-backed topology | `S1_MER_ENERGIE_CO2_2025` Appendix A1 | 45 bar steam from Centrale 2 can be reduced to 15 bar. |
| `STEAM_72_TO_15_BYPASS_ALLOWED` | true | bool | source-backed topology | `S1_MER_ENERGIE_CO2_2025` Appendix A1 | Parallel reducers can feed 15 bar when TG2 is stopped. |
| `STEAM_REDUCTION_ELECTRICITY_RECOVERY` | 0 for bypass; TG2 only for recovery | policy | modelling choice | `S1_MER_ENERGIE_CO2_2025` | Pressure reducers do not generate electricity. TG2 does. |
| `STEAM_STORAGE_ACTIVE_BASE` | false | bool | policy | `S5_PROJECT_GOVERNANCE` | Steam is a bus, not a store, unless explicit source evidence supports storage. |
| `STEAM_SURPLUS_BLOWOFF_ALLOWED_DIAGNOSTIC` | true | bool | diagnostic | `S1_MER_ENERGIE_CO2_2025` system logic | Prevents infeasibility in smoke tests; must be reported and penalised/caveated. |
| `STEAM_UNSERVED_ALLOWED_BASE` | false | bool | policy | model policy | Steam demand should be hard met in thesis-usable runs. Any unmet steam should trigger infeasibility or explicit diagnostic. |
| `STEAM_RESIDUAL_DEMAND_ACTIVE` | true | bool | base modelling policy | `S4_ATHANASIADIS_2025`, `S5_PROJECT_GOVERNANCE` | Residual/unmodelled steam users should be reported, not assumed zero. |

---

## Recommended first implementation equations

### Boiler fuel controller

For each boiler group `b` and gas `g`:

```text
fuel_to_boiler[b,g,t] <= available_gas[g,t]
fuel_heat_boiler[b,t] = sum_g fuel_to_boiler[b,g,t]
```

Allowed fuels:

```text
K15_K16: BFG, COG, NG
K23_K24: BFG, COG, NG
K41:     BFG, NG
```

### Boiler steam output

Using a mass-steam carrier:

```text
steam_out_K15K16[t] = fuel_heat_K15K16[t] / 0.876
steam_out_K23K24[t] = fuel_heat_K23K24[t] / 0.861
steam_out_K41[t]    = fuel_heat_K41[t]    / 0.700
```

Capacity constraints:

```text
steam_out_K15K16[t] <= 220
steam_out_K23K24[t] <= 220
steam_out_K41[t]    <= 80
```

These ratios are source-table-derived from MWth and t/h steam. They are effective accounting coefficients, not independent boiler efficiency estimates.

### STEG11 CHP

If dispatch is by fuel input:

```text
fuel_heat_STEG11[t] <= 85
steam_72_STEG11[t] = fuel_heat_STEG11[t] * 0.941
power_STEG11[t]    = fuel_heat_STEG11[t] * 0.154
steam_72_STEG11[t] <= 80
power_STEG11[t]    <= 13.1
```

If dispatch is by steam output:

```text
fuel_heat_STEG11[t] = steam_72_STEG11[t] * 1.063
power_STEG11[t]     = steam_72_STEG11[t] * 0.164
steam_72_STEG11[t] <= 80
```

Recommended first version: dispatch by fuel input or steam demand, but keep `STEG11_MARKET_ELECTRICITY_REVENUE_ACTIVE=false`.

### TG2 steam turbine

Simplified main route:

```text
steam_72_to_TG2[t] <= 105
power_TG2[t]       = steam_72_to_TG2[t] * 0.138
steam_15_from_TG2[t] = steam_72_to_TG2[t]
power_TG2[t] <= 14.5
```

Optional low-pressure stream is deferred because the public table gives both 15 bar and 0.5 bar streams but does not give enough information for a rigorous extraction split in the first model.

### Bypass reducers

```text
steam_72_to_45[t] >= 0
steam_72_to_15_bypass[t] >= 0
steam_45_to_15[t] >= 0
```

For first mass-flow accounting, set output mass equal to input mass. Do not claim thermodynamic power recovery from reducers.

### Steam bus balances

```text
steam_72_supply[t] =
    steam_out_K15K16[t]
  + steam_72_STEG11[t]

steam_72_demand[t] =
    steam_72_to_TG2[t]
  + steam_72_to_45[t]
  + steam_72_to_15_bypass[t]
  + steam_72_direct_loads[t]
  + steam_72_spill[t]

steam_45_supply[t] =
    steam_out_K23K24[t]
  + steam_out_K41[t]
  + steam_72_to_45[t]

steam_45_demand[t] =
    steam_45_process_loads[t]
  + steam_45_to_15[t]
  + steam_45_spill[t]

steam_15_supply[t] =
    steam_15_from_TG2[t]
  + steam_72_to_15_bypass[t]
  + steam_45_to_15[t]

steam_15_demand[t] =
    steam_15_process_loads[t]
  + steam_15_spill[t]
```

Where detailed load allocation is missing, use explicitly named residual steam loads rather than hiding the gap.

---

## 2026 source repair update - boiler efficiency and operational detail assumptions

This update records governed development assumptions for boiler efficiency
sensitivity and explicitly keeps ramp, minimum-load and reserve logic deferred.
It does not replace the source-table-derived fuel/steam ratios used in the
first boiler/steam implementation, does not retune WAG balances, and does not
activate new executable inputs by itself.

| Parameter ID | Value / range | Unit | Original basis | Converted basis / derivation | Status label | Recommended model use | Source title, authors/organisation, year, URL/DOI | Locator status | Caveat |
|---|---:|---|---|---|---|---|---|---|---|
| `BOILER_EFFICIENCY_BASE` | 0.85 | fraction fuel energy to useful steam energy | Governed project assumption for first sensitivity framing | no conversion | governed_assumption | development_input_candidate / sensitivity_range | Project governance and boiler source-card repair note, 2026 | not_applicable | No Tata-specific efficiency source found; MER Energie gives boiler thermal and steam capacities, but not verified fuel-to-steam efficiency. Use only as governed sensitivity framing before thesis claims. |
| `BOILER_EFFICIENCY_LOW` | 0.80 | fraction fuel energy to useful steam energy | Governed low sensitivity | no conversion | governed_assumption | sensitivity_range | Project governance and boiler source-card repair note, 2026 | not_applicable | Do not use to calibrate WAG balances to anchors in this task. |
| `BOILER_EFFICIENCY_HIGH` | 0.90 | fraction fuel energy to useful steam energy | Governed high sensitivity | no conversion | governed_assumption | sensitivity_range | Project governance and boiler source-card repair note, 2026 | not_applicable | No source-backed Tata efficiency claim. |
| `BOILER_RAMP_LIMIT` | deferred | t/h/h or MW/h | No reviewed public ramp evidence | n/a | not_found | deferred | Project governance and boiler source-card repair note, 2026 | not_applicable | Avoid false precision and extra binaries until source-backed ramp/min-load evidence exists. |
| `BOILER_MIN_LOAD` | deferred | fraction | No reviewed public minimum-stable-load evidence | n/a | not_found | deferred | Project governance and boiler source-card repair note, 2026 | not_applicable | Do not add minimum-load constraints without source review. |
| `BOILER_MFRR_ENABLED_BASE` | false | bool | Project market-scope policy | n/a | governed_assumption | deferred | Project governance and boiler source-card repair note, 2026 | not_applicable | Boilers/STEG11/TG2 are not base reserve assets; no mFRR in this stage. |

Existing fuel eligibility remains unchanged: K15/K16 use BFG + COG + NG,
K23/K24 use BFG + COG + NG, K41 uses BFG + NG, TG2 is steam-only, and STEG11
follows the already documented steam-circuit eligibility. Boiler efficiencies
are sensitivity/governance rows only and must not become hidden calibration
plugs.

---

## Model abstraction choices and rationale

### Why group K15/K16 but split K23/K24 from K41?

K15 and K16 are similar in Table 0.1: both 96.4 MWth, 110 t/h, 72 bar(g), 505 °C. They also share source-backed BFG/COG eligibility. Grouping them is therefore a reasonable first abstraction.

K23 and K24 are similar enough to group, but K41 is materially different:

- lower capacity: 80 t/h instead of 110 t/h;
- lower MWth: 56 MWth;
- source-backed fuel eligibility is BFG, while COG is not listed in the QRA COG consumer list for K41;
- user policy allows NG for K41, but not COG.

Therefore K41 remains a separate Link group.

### Why not fully model the steam thermodynamics?

A rigorous steam network would require enthalpy, pressure drops, turbine extraction/condensing behaviour, reducer losses, steam quality and exact process steam demands. The public sources give pressure/temperature/capacity, but not a complete dispatchable thermodynamic model.

The first implementation therefore uses:

- steam mass balances by pressure level;
- source-table-derived fuel/steam ratios;
- explicit pressure-reduction links;
- diagnostic steam spill.

This is accurate enough to represent functionality and WAG/NG use without false precision.

### Why not treat TG2/STEG11 as market generators?

TG2 and STEG11 produce electricity, but in this layer their role is to close the steam circuit and represent internal electricity offsets. Allowing them to chase DA prices before the steam/WAG boundary is validated could make electricity arbitrage dominate the steel process.

For thesis use, activate electricity value only through a later explicit economic policy gate.

### Why keep steam spill?

Steam spill/blow-off is useful for model diagnostics and smoke tests. It prevents the first implementation from becoming infeasible solely because a small residual steam sink is missing. But it must be visible, limited or penalised, and never hidden as free disposal.

---

## Validation anchors

### Long-term/full-model anchors

| Anchor | Value / description | Use |
|---|---:|---|
| Centrale 1 contains GT11+AK11, K15, K16 and TG2 | qualitative | Topology validation. |
| Centrale 2 contains K23, K24, K41 and windmachines | qualitative | Topology validation. |
| Centrale 1 steam levels | 72, 45, 15, 0.5 bar(g) | Pressure-level validation. |
| Centrale 2 steam level | 45 bar(g) main, plus 15 bar(g) process steam | Pressure-level validation. |
| K15/K16 capacity | 220 t/h, 192.8 MWth | C1 steam capacity validation. |
| K23/K24 capacity | 220 t/h, 189.3 MWth | C2 steam capacity validation. |
| K41 capacity | 80 t/h, 56 MWth | K41 validation. |
| STEG11 capacity | 85 MWth, 13.1 MWe, 80 t/h steam | CHP validation. |
| TG2 capacity | 14.5 MWe, 105 t/h main steam route | Steam-turbine validation. |
| BFG consumer list | STEG11, K15, K16, K23, K24, K41 | WAG sink eligibility validation. |
| COG consumer list | K15, K16, K23, K24 | COG sink eligibility validation. |
| NG network to Tata/ENB | qualitative | NG-backup feasibility, caveated. |

### Small first-implementation checks

| Check | Use |
|---|---|
| `steam_supply_by_pressure_level` | Identify whether boiler/TG topology closes steam buses. |
| `steam_demand_by_process` | Prevent unallocated steam demand from being hidden. |
| `fuel_use_by_boiler_group` | Check BFG/COG/NG allocation and WAG scarcity. |
| `ng_use_for_steam` | External fuel-cost layer / sensitivity. |
| `steam_spill_by_pressure_level` | Detect missing sinks or overproduction. |
| `STEG11_power_output` | Internal electricity offset, not market profit. |
| `TG2_power_output` | Pressure-reduction recovery, not market profit. |
| `WAG_to_steam_vs_WAG_to_other_sinks` | Check whether boilers are dominating WAG allocation. |

---

## Caveats and red flags

1. Do not use this layer to create direct WAG market revenue.
2. Do not let STEG11/TG2 dominate DA optimisation before the common C0/C1 economic policy is stable.
3. Do not treat steam as a Store unless a physical steam accumulator or storage source is added.
4. Do not hide steam spill or unmet steam inside unnamed slack variables.
5. Do not infer boiler efficiencies from generic literature when source-table capacity ratios already provide a safer first approximation.
6. Do not treat NG eligibility as equally source-strong as BFG/COG eligibility. NG is included because the site network and modelling policy support it, but per-burner public evidence is weaker.
7. Do not add COG to K41 or STEG11 in the first implementation unless later source evidence supports it.
8. Do not model mFRR from boilers, TG2 or STEG11 in the base layer.
9. If pressure levels are collapsed to one `steam_utility` bus for smoke tests, report that as an engineering simplification and rerun pressure-level validation before thesis claims.

---

## Source notes with exact values

### `S1_MER_ENERGIE_CO2_2025`

- Full source: Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025). *Detailstudie Energie en CO2-balans, MER Heracless - Groen Staal*. Reference `BI3580-IB-RP`, Definitief, 15 September 2025. URL: https://pas.commissiemer.nl/files/nl/3730/01-Energie.pdf
- Relevant section: Appendix A1, *Energiebedrijf Tata Steel (KEMA, 2010)*.
- Relevant content:
  - ENB includes `GT11 + AK11`, TG2 and boilers K15/K16/K41/K23/K24/K33/K34/K35.
  - Centrale 1 tasks: supply 72, 45, 15 and 0.5 bar(g) steam; steam/electricity island operation; backup steam for Centrale 2; start steam for IJmond-01.
  - Centrale 1 has STEG installation, two steam boilers and one turbo-generator; STEG consists of gas turbine with generator GT11 and exhaust-gas boiler AK11.
  - AK11, K15 and K16 deliver 72 bar(g) steam over TG2, reducing to 15 and 0.5 bar(g), converting released energy into electric power.
  - 72 bar(g) steam can supplement the 45 bar(g) steam net; 45 bar(g) steam can be reduced to 15 bar(g); parallel steam reducers can feed 15 bar when TG2 is stopped.
  - Centrale 2 main task is blast wind for blast furnaces via 45 bar(g) steam-driven wind machines; also supplies process/heating steam to KGF2, OSF2 and HO6/HO7.
  - Table 0.1 values used in this memo:
    - TG2: 14.5 MWe, 105 t/h at 15 bar(g), 350 °C; 20 t/h at 0.5 bar(g), 175 °C.
    - K15: 96.4 MWth, 110 t/h, 72 bar(g), 505 °C.
    - K16: 96.4 MWth, 110 t/h, 72 bar(g), 505 °C.
    - STEG11: 85 MWth, 13.1 MWe, 80 t/h, 72 bar(g), 505 °C.
    - K41: 56 MWth, 80 t/h, 45 bar(g), 465 °C.
    - K23: 96.2 MWth, 110 t/h, 45 bar(g), 465 °C.
    - K24: 93.1 MWth, 110 t/h, 45 bar(g), 465 °C.
- Caveat: the table is sufficient for capacities and pressure levels, but not a complete thermodynamic dispatch model.

### `S2_QRA_REFERENTIE_2025`

- Full source: Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025). *Detailstudie Externe Veiligheid - QRA actuele bedrijfssituatie, MER Heracless*. Reference `BI3580-IB-RP`, Definitief, 15 September 2025. URL: https://pas.commissiemer.nl/files/nl/3730/11-a-Veiligheid-referentie.pdf
- Relevant section: §6.3, transportleidingen / gas networks.
- Relevant content:
  - BFG is cooled/cleaned before use and is used as fuel gas in other installations; BFG holder buffers variation.
  - Internal Tata BFG consumers: Centrale 1 `STEG11 (AK11)`, Ketel 15 and Ketel 16; Centrale 2 Ketel 23 and Ketel 24; Centrale 4 Afgassenketel 41 and Kofa 1.
  - COG is cleaned before fuel use and sent to consumers including Warmbandwalserij, Hoogovens, PeFa, SiFa, Ketels Centrale 1 and 2: K15, K16, K23 and K24, BFG enrichment and start-up IJM01.
  - Natural-gas network exists on the Tata site and supplies various locations including ENB-related areas; per-boiler NG eligibility is not specified with the same clarity as BFG/COG.
- Caveat: QRA is safety/topology source, not a dispatch or efficiency source.

### `S3_QRA_HERACLESS_2025`

- Full source: Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025). *Detailstudie Externe Veiligheid - QRA Heracless, MER Heracless*. Reference `BI3580-IB-RP`, Definitief, 15 September 2025. URL: https://pas.commissiemer.nl/files/nl/3730/11-b-Veiligheid-Heracless.pdf
- Relevant section: §6.4.3.1 Hoogovengasnetwerk.
- Relevant content:
  - With Heracless, BFG production decreases but composition does not change significantly.
  - Internal Tata BFG consumers remain: Windverhitter HO6; Centrale 1 `STEG11 (AK11)`, K15, K16; Centrale 2 K41, K23 and K24.
- Caveat: confirms C1 topology but not operating levels.

### `S4_ATHANASIADIS_2025`

- Full source: Athanasiadis, I. (2025). *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel’s IJmuiden Site*. TU Delft MSc thesis.
- Relevant content:
  - WAGs are tracked from production to consumers such as main plants, boilers for steam generation and Vattenfall electricity generators.
  - The gas network is simplified because real gas-holder and Wobbe-index dynamics are faster than an hourly simulation.
  - Figure 32 shows boilers consuming WAG mixtures via controllers to satisfy site steam demand.
- Caveat: modelling precedent only. Do not promote redacted or model-internal values to exact Tata source-backed inputs.

---

## Suggested next migration target

If this source-card is accepted, the executable input migration should create rows for:

- `steam_buses.csv`
- `utility_conversion_assets.csv`
- `wag_sink_eligibility.csv`
- `utility_demands.csv`
- `steam_pressure_reducers.csv` or equivalent Link rows
- `validation_anchors.csv`

Minimum required executable rows:

```text
BOILER_C1_K15K16
BOILER_C2_K23K24
BOILER_C2_K41
STEG11_CHP
TG2_STEAM_TURBINE
STEAM_72_TO_45_REDUCER
STEAM_72_TO_15_REDUCER
STEAM_45_TO_15_REDUCER
STEAM_SPILL_DIAGNOSTIC
```

All rows should carry `source_card_ids`, `input_status`, `thesis_usability`, `caveat`, and `human_review_required` fields.
