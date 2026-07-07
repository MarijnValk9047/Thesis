# Steel WAG, Steam, Natural-Gas, Boiler, Vattenfall-Interface, and Flaring Abstraction

**Status:** design note / modelling contract candidate
**Suggested repo path:** `docs/optimisation/steel/S4/STEEL_WAG_STEAM_GAS_NETWORK_ABSTRACTION.md`
**Scope:** `C0_current_BF_BOF_reference` and `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`
**Main C1 topology decision:** `BF7` and `KGF2 / Coking Plant 2` inactive; `BF6` and `KGF1 / Coking Plant 1` retained.
**Purpose:** define one controlled, PyPSA-style representation of the internal WAG/steam/gas layer for the public Tata-inspired steel MILP without claiming to reproduce Tata's confidential gas-network operation.

---

## 1. Modelling position

This model uses Athanasiadis as the **architecture precedent**, not as permission to recreate a confidential gas-network digital twin. The real IJmuiden gas system includes gas holders, gas stations, fuel-quality control, Wobbe-index management, boiler-specific requirements, generator contracts, and sub-hourly operational controls. Those details are not publicly reconstructable in a thesis-grade way.

The selected representation is therefore a **semi-detailed, bounded WAG accounting layer**:

- `BFG`, `COG`, and `BOFG` remain separate carriers.
- Work-arising gases are produced by steel-process `Links`.
- Direct process consumers such as the Sinter Plant and Coking Plants are included.
- Flexible gas-mixing consumers are represented through eligibility and bounded fuel Links, not full gas-station control logic.
- Steam is represented through an aggregated utility/boiler system.
- Vattenfall is represented as a constrained interface, not a merchant generator controlled by the optimiser.
- Flaring is explicit and reported.
- No WAG storage is allowed at hourly resolution.
- Missing/redacted values remain visible as missing, provisional, or development-only assumptions.

The guiding rule is:

> Missing gas-network detail may close balances, but it may not create new price-responsive flexibility, hidden WAG revenue, or unsupported internal-energy arbitrage.

---

## 2. Evidence and governance basis

### 2.1 Source hierarchy

Use the existing project hierarchy:

1. Formal public Tata/MER/eMJV-style sources and registered source cards for public topology and numeric evidence.
2. Athanasiadis as public-thesis modelling-architecture precedent for PyPSA process, gas, WAG, steam, CO2, and Store structure.
3. Badarinath as secondary precedent for electricity-market abstraction, DRP/EAF flexibility framing, and the BF7/KGF2 C1 closure interpretation used in this project.
4. Repository freeze, roadmap, model-policy, assumption-register, and stage-gate documents for selected boundary decisions.
5. Generic engineering literature only for candidate ranges and sensitivity values, never as exact Tata truth.

### 2.2 Source-to-input workflow

No number in this document is automatically executable. Use this workflow:

1. Source -> source card.
2. Value or range -> candidate evidence register.
3. Modelling interpretation -> assumption register.
4. Physical structure -> physical master workbook.
5. Review output -> compiled review CSVs.
6. Executable use -> reviewed migration into development input tables.
7. Thesis use -> later approval gate.

### 2.3 Data-status labels

Use these labels in all tables and input rows:

| Status | Meaning |
|---|---|
| `public_exact` | Public, directly cited value; still not hardcoded in Python. |
| `public_interpreted` | Derived from public text/figure; derivation must be recorded. |
| `development_assumption` | Safe engineering assumption for smoke tests or guarded development. |
| `sensitivity_only` | Parameter exists only to test robustness. |
| `redacted_or_unavailable` | Known required input, but not publicly available. |
| `deferred` | Structurally recognised but not active in the base model. |
| `forbidden_base` | Not allowed in the base objective or base dispatch. |

---

## 3. PyPSA terminology used in this note

The implementation is PyPSA-inspired even if the executable model is in Pyomo.

| PyPSA term | Meaning in this abstraction |
|---|---|
| `Bus` | Balance node for a material, energy carrier, utility carrier, or accounting node. |
| `Link` | Process, conversion, allocation, mixing, boiler, flare, or interface component. |
| `Generator` | Exogenous supply with an external cost, e.g. grid electricity or natural gas. |
| `Load` | Exogenous withdrawal or residual demand not controlled by the optimiser. |
| `Store` | Physical buffer only when finite capacity and terminal policy are defined. CO2 accumulator is accounting, not flexibility. |
| `Link bus0` | Main input or reference input of a process/conversion Link. |
| `Link bus1, bus2, ...` | Outputs or additional ports of a multi-input/multi-output process. |
| `p_nom` | Nominal capacity of a process/conversion/allocation Link. |
| `p_min_pu`, `p_max_pu` | Operating range as fraction of `p_nom`. |
| `ramp_limit_up`, `ramp_limit_down` | Hourly ramp limits where retained. |
| `efficiency` / conversion factor | Coefficient linking `bus0` activity to other buses. In this note, most gas allocation is energy-normalised, so many gas-to-fuel efficiencies are `1.0`. |

---

## 4. Configuration scope

### 4.1 `C0_current_BF_BOF_reference`

Active WAG-producing process Links:

| Link | Active in C0 | WAG output |
|---|---:|---|
| `Link_KGF1_CokingPlant1` | yes | `COG` |
| `Link_KGF2_CokingPlant2` | yes | `COG` |
| `Link_BF6` | yes | `BFG` |
| `Link_BF7` | yes | `BFG` |
| `Link_BOF` | yes | `BOFG` |

### 4.2 `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`

Active and inactive WAG-producing process Links:

| Link | Active in C1 | WAG output |
|---|---:|---|
| `Link_KGF1_CokingPlant1` | yes | `COG` |
| `Link_KGF2_CokingPlant2` | **no** | none |
| `Link_BF6` | yes | `BFG` |
| `Link_BF7` | **no** | none |
| `Link_BOF` | yes, if BOF route active | `BOFG` |
| `Link_NG_DRP` | yes | none in base |
| `Link_EAF` | yes | none in base |

This document uses the project-corrected C1 definition: **Coking Plant 2 / KGF2 and BF7 shut down**. It does not use the alternative wording in Athanasiadis that can be read as closing Coking Plant 1.

---

## 5. Hard public carrier constants

### 5.1 Lower heating values

Use these lower heating values from Athanasiadis's gas-network figures as public constants.

| Carrier | Symbol | LHV | MWh/Nm3 equivalent | Status |
|---|---:|---:|---:|---|
| Blast Furnace Gas | `BFG` | `3.85 MJ/Nm3` | `0.001069444 MWh/Nm3` | `public_exact` |
| Basic Oxygen Furnace Gas | `BOFG` | `8.6 MJ/Nm3` | `0.002388889 MWh/Nm3` | `public_exact` |
| Coke Oven Gas | `COG` | `18.5 MJ/Nm3` | `0.005138889 MWh/Nm3` | `public_exact` |
| Natural Gas | `NG` | `37.5 MJ/Nm3` | `0.010416667 MWh/Nm3` | `public_exact` |

Conversion:

```text
MWh_LHV = Nm3 * LHV_MJ_per_Nm3 / 3600
Nm3 = MWh_LHV * 3600 / LHV_MJ_per_Nm3
```

### 5.2 Ratios retained for Athanasiadis traceability

These ratios should be stored in the carrier/conversion parameter table. They are mainly for traceability to Athanasiadis's mixing-controller logic. The base model uses energy-normalised MWh-LHV flows, so most gas-to-fuel allocation Links have efficiency `1.0`.

| Conversion | Ratio | Value |
|---|---:|---:|
| `NG` to COG-equivalent | `37.5 / 18.5` | `2.027027` |
| `BOFG` to COG-equivalent | `8.6 / 18.5` | `0.464865` |
| `BFG` to COG-equivalent | `3.85 / 18.5` | `0.208108` |
| `COG` to BFG-equivalent | `18.5 / 3.85` | `4.805195` |
| `BOFG` to BFG-equivalent | `8.6 / 3.85` | `2.233766` |
| `NG` to BFG-equivalent | `37.5 / 3.85` | `9.740260` |
| `COG` to 5 MJ/Nm3 generator-gas equivalent | `18.5 / 5` | `3.700000` |
| `BOFG` to 5 MJ/Nm3 generator-gas equivalent | `8.6 / 5` | `1.720000` |
| `NG` to 5 MJ/Nm3 generator-gas equivalent | `37.5 / 5` | `7.500000` |
| `BFG` to 5 MJ/Nm3 generator-gas equivalent | `3.85 / 5` | `0.770000` |

---

## 6. Buses

### 6.1 Carrier Buses

| Bus name | Carrier | Internal unit | Role |
|---|---|---:|---|
| `Bus_BFG` | Blast Furnace Gas | `MWh_LHV/h` | BFG produced by BF process Links. |
| `Bus_COG` | Coke Oven Gas | `MWh_LHV/h` | COG produced by coking process Links. |
| `Bus_BOFG` | Basic Oxygen Furnace Gas | `MWh_LHV/h` | BOFG produced by BOF process Link. |
| `Bus_NaturalGas` | Natural Gas | `MWh_LHV/h` | External natural-gas supply. |
| `Bus_Electricity` | Electricity | `MWh/h` | Site electricity bus where full electricity balance is active. |
| `Bus_CO2` | CO2 | `tCO2/h` | Process, combustion, residual, and flaring emissions. |

### 6.2 Process-fuel Buses

| Bus name | Internal unit | Role | Base activation |
|---|---:|---|---|
| `Bus_Fuel_Sinter` | `MWh_LHV/h` | Direct Sinter Plant COG-equivalent fuel demand. | active if Sinter active |
| `Bus_Fuel_KGF1` | `MWh_LHV/h` | Coking Plant 1 WAG/COG underfiring demand. | active if KGF1 active |
| `Bus_Fuel_KGF2` | `MWh_LHV/h` | Coking Plant 2 COG underfiring demand. | active in C0 only |
| `Bus_Fuel_HSM` | `MWh_LHV/h` | HSM COG/NG process-fuel demand. | eligible, parameter-gated |
| `Bus_Fuel_PEFA_Malerij` | `MWh_LHV/h` | Pelletizing Malerij BOFG/NG fuel demand. | eligible, parameter-gated |
| `Bus_Fuel_PEFA_Branderij` | `MWh_LHV/h` | Pelletizing Branderij COG/NG fuel demand. | eligible, parameter-gated |

### 6.3 Utility and interface Buses

| Bus name | Internal unit | Role | Base activation |
|---|---:|---|---|
| `Bus_BoilerFuel` | `MWh_LHV/h` | Aggregated boiler-fuel pool. | active |
| `Bus_Steam` | `MWh_th/h` | Steam balance. No Steam Store in base. | active |
| `Bus_VattenfallFuel` | `MWh_LHV/h` | WAG fuel sent to Vattenfall/interface sink. | reporting/interface only |
| `Bus_ElectricityFromWAG_reporting` | `MWh/h` | Reporting proxy for possible WAG electricity. | reporting only |
| `Bus_Flare_BFG` | `MWh_LHV/h` | Diagnostic flared BFG. | optional diagnostic |
| `Bus_Flare_COG` | `MWh_LHV/h` | Diagnostic flared COG. | optional diagnostic |
| `Bus_Flare_BOFG` | `MWh_LHV/h` | Diagnostic flared BOFG. | optional diagnostic |

---

## 7. Generators

| Generator | Bus | Unit | Cost treatment | Status |
|---|---|---:|---|---|
| `Generator_NaturalGasMarket` | `Bus_NaturalGas` | `MWh_LHV/h` | `c_NG_t` if NG objective active. | active where NG use is modelled |
| `Generator_ElectricityMarket` | `Bus_Electricity` | `MWh/h` | `lambda_DA_t` if electricity objective active. | stage-dependent |
| `Generator_ResidualCO2` | `Bus_CO2` | `tCO2/h` | reporting or ETS sensitivity. | optional |

Rules:

- Natural gas is an external cost when explicitly consumed.
- Electricity is an external cost only when the full or partial electricity boundary is active.
- Residual CO2 is accounting/reporting unless a reviewed carbon-cost convention is active.
- No WAG carrier has a market `Generator` or direct sale value in the base model.

---

## 8. Stores

### 8.1 No WAG Stores

No `Store` is created for:

- `BFG`;
- `COG`;
- `BOFG`;
- mixed WAGs;
- `Bus_BoilerFuel`;
- `Bus_VattenfallFuel`.

The hourly model must balance WAG production and consumption within every timestep. Any surplus must be allocated to eligible sinks or flared.

### 8.2 No Steam Store in base

`Bus_Steam` is a balance node. Steam storage is not active unless a finite steam-storage capacity, pressure-level boundary, and terminal policy are sourced and approved.

### 8.3 CO2 accumulator

| Store | Bus | Role | Flexibility? |
|---|---|---|---|
| `Store_CO2_Accumulator` | `Bus_CO2` | Accumulates direct, combustion, residual, and flaring emissions. | no |

The CO2 accumulator is an accounting device, not a physical store that can shift emissions.

---

## 9. WAG production Links

WAG production is tied to process activity. It must not be independent dispatch.

### 9.1 Coking plants: COG production

| Link | Main activity basis | WAG output | Active C0 | Active C1 | Required coefficient |
|---|---|---|---:|---:|---|
| `Link_KGF1_CokingPlant1` | dry coal input or coke output, basis to be frozen | `Bus_COG` | yes | yes | `alpha_COG_KGF1` |
| `Link_KGF2_CokingPlant2` | dry coal input or coke output, basis to be frozen | `Bus_COG` | yes | no | `alpha_COG_KGF2` |

Generic form:

```text
COG_prod_KGFp[t] = x_KGFp[t] * alpha_COG_KGFp
```

Status:

- Exact Tata/Athanasiadis plant-specific coefficients are redacted or unavailable.
- Development-only candidate: `350 Nm3 COG / t coke` at `18.5 MJ/Nm3` = `1.7986 MWh_LHV/t coke`.
- Sensitivity: `300-400 Nm3/t coke` = `1.5417-2.0556 MWh_LHV/t coke`.

### 9.2 Blast furnaces: BFG production

| Link | Main activity basis | WAG output | Active C0 | Active C1 | Required coefficient |
|---|---|---|---:|---:|---|
| `Link_BF6` | hot metal output | `Bus_BFG` | yes | yes | `alpha_BFG_BF6` |
| `Link_BF7` | hot metal output | `Bus_BFG` | yes | no | `alpha_BFG_BF7` |

Generic form:

```text
BFG_prod_BFp[t] = HM_BFp[t] * alpha_BFG_BFp
```

Status:

- Exact furnace-specific coefficients are redacted or unavailable.
- Development-only candidate: `1500 Nm3 BFG / t hot metal` at `3.85 MJ/Nm3` = `1.6042 MWh_LHV/t HM`.
- Sensitivity: `1300-1800 Nm3/t HM` = `1.3903-1.9250 MWh_LHV/t HM`.

### 9.3 Basic Oxygen Furnace: BOFG production

| Link | Main activity basis | WAG output | Active C0 | Active C1 | Required coefficient |
|---|---|---|---:|---:|---|
| `Link_BOF` | BOF liquid steel or crude steel output | `Bus_BOFG` | yes | yes if BOF route active | `alpha_BOFG_BOF` |

Generic form:

```text
BOFG_prod_BOF[t] = BOF_output[t] * alpha_BOFG_BOF
```

Status:

- Exact BOFG recovery coefficient is redacted or unavailable.
- Development-only candidate: `80 Nm3 BOFG / t BOF steel` at `8.6 MJ/Nm3` = `0.1911 MWh_LHV/t BOF steel`.
- Sensitivity: `50-120 Nm3/t BOF steel` = `0.1194-0.2867 MWh_LHV/t BOF steel`.
- Include `0` recovery as a stress sensitivity if BOFG recovery is not reliable.

---

## 10. Important correction: WAG/COG consumers are broader than the four main gas controllers

Earlier shorthand that Athanasiadis has “four main WAG-consuming plants” is incomplete. The correct distinction is:

1. Athanasiadis Figure 31 has **four flexible main-plant gas-mixing controller groups**:
   - `Controller Coking Plant 1`;
   - `Controller Hot Strip Mill`;
   - `Controller PEFA Malerij`;
   - `Controller PEFA Branderij`.
2. Other individual process Links also consume COG or WAG-related fuel directly:
   - Sinter Plant consumes `COG` in its process Link.
   - Coking Plant 2 consumes `COG` in its process Link.
   - Coking Plant 1 consumes `WAGs COK1`, a BFG/COG mixture.
3. The boiler and Vattenfall subsystems consume WAGs separately from the main-plant controller figure.

Therefore, the model's WAG balance must include:

- direct process-linked COG/WAG demand;
- flexible or semi-fixed main-plant fuel sinks;
- steam/boiler demand;
- Vattenfall/interface demand;
- flaring.

---

## 11. Direct process-linked WAG/COG sinks

These sinks are not optional. They close the COG/WAG accounting for the main process chain. They should be represented as process-linked fuel demand rather than as free price-responsive dispatch.

### 11.1 Sinter Plant direct COG use

Athanasiadis shows the Sinter Plant as a `Link` with inputs including `Iron Ore`, `Electricity`, `COG`, and `Steam`, and outputs including `Sinter` and `CO2`.

Base representation:

| Link | bus0 | bus1 | Efficiency | Role |
|---|---|---|---:|---|
| `Link_COG_to_Fuel_Sinter` | `Bus_COG` | `Bus_Fuel_Sinter` | `1.0` | COG fuel into Sinter Plant process demand. |
| `Link_SinterPlant` | material/process buses | `Sinter`, `CO2`, utility demands | process coefficients | Main Sinter Plant process Link. |

Demand form:

```text
Fuel_Sinter[t] = Sinter_activity[t] * alpha_fuel_COG_Sinter
```

Safe assumption:

- Use fixed process-linked COG demand, not optimised COG/NG switching.
- Development-only candidate: `0.10 GJ_LHV/t sinter` = `0.02778 MWh_LHV/t sinter`.
- Sensitivity: `0`, `0.05`, `0.15`, `0.25 GJ/t sinter`.
- If this demand is material to results, source repair is required before thesis use.

### 11.2 Coking Plant 1 WAG/COG use

Athanasiadis represents Coking Plant 1 as consuming a plant-specific WAG mixture `WAGs COK1`, supplied by a mixing gas station using `BFG` and `COG`.

Base representation:

| Link | bus0 | bus1 | Efficiency | Role |
|---|---|---|---:|---|
| `Link_BFG_to_Fuel_KGF1` | `Bus_BFG` | `Bus_Fuel_KGF1` | `1.0` | BFG contribution to KGF1 underfiring. |
| `Link_COG_to_Fuel_KGF1` | `Bus_COG` | `Bus_Fuel_KGF1` | `1.0` | COG contribution to KGF1 underfiring. |
| `Link_KGF1_CokingPlant1` | coal/process buses | `Coke`, `COG`, `CO2`, utility demands | process coefficients | Main KGF1 process Link. |

Demand form:

```text
Fuel_KGF1[t] = KGF1_activity[t] * alpha_fuel_KGF1
```

Safe assumption:

- Keep KGF1 underfiring as a fixed process-linked demand.
- Allow `BFG` and `COG` as eligible fuels, but do not let electricity prices determine the split.
- Development-only candidate for total underfiring: `3.5 GJ_LHV/t coke` = `0.9722 MWh_LHV/t coke`.
- Sensitivity: `3.0-4.0 GJ/t coke`.
- If no source exists for BFG/COG split, use a fixed split or hierarchy and test sensitivity:
  - base placeholder: `50% BFG / 50% COG` on energy basis;
  - sensitivity: `100% COG`, `100% BFG`, and `75/25` variants.

### 11.3 Coking Plant 2 direct COG use

Athanasiadis shows Coking Plant 2 as a `Link` with inputs including `Coal`, `COG`, `Steam`, and `Electricity`, and outputs including `Coke`, `COG`, and `CO2`.

Base representation:

| Link | bus0 | bus1 | Efficiency | Active C0 | Active C1 |
|---|---|---|---:|---:|---:|
| `Link_COG_to_Fuel_KGF2` | `Bus_COG` | `Bus_Fuel_KGF2` | `1.0` | yes | no |
| `Link_KGF2_CokingPlant2` | coal/process buses | `Coke`, `COG`, `CO2`, utility demands | process coefficients | yes | no |

Demand form:

```text
Fuel_KGF2[t] = KGF2_activity[t] * alpha_fuel_KGF2
```

Safe assumption:

- In C0, represent CP2 COG use as fixed process-linked demand.
- In C1, `KGF2` is inactive, so both CP2 COG production and CP2 COG consumption are zero.
- Development-only candidate for total underfiring: same as KGF1 unless better source exists, `3.5 GJ_LHV/t coke`.
- Sensitivity: `3.0-4.0 GJ/t coke`.

---

## 12. Flexible or semi-fixed main-plant fuel sinks

These are Athanasiadis Figure 31 gas-mixing controller groups. For our model, they are retained as eligibility rows and either fixed process-linked demands or tightly bounded substitution variables. They must not become free gas arbitrage assets.

### 12.1 Hot Strip Mill fuel

Athanasiadis controller: `COG` or `Natural Gas` -> `WAGs HSM` -> `Hot Strip Mill`.

| Link | bus0 | bus1 | Efficiency in energy-normalised base |
|---|---|---|---:|
| `Link_COG_to_Fuel_HSM` | `Bus_COG` | `Bus_Fuel_HSM` | `1.0` |
| `Link_NG_to_Fuel_HSM` | `Bus_NaturalGas` | `Bus_Fuel_HSM` | `1.0` |

Demand form:

```text
Fuel_HSM[t] = HSM_activity[t] * alpha_fuel_HSM
```

Status:

- `alpha_fuel_HSM` is redacted or unavailable.
- Do not activate as a flexible optimisation sink until a candidate value and bounds are reviewed.
- Safe base: record eligibility; use aggregate residual/process-heat demand if needed.

### 12.2 Pelletizing Plant Malerij fuel

Athanasiadis controller: `BOFG` or `Natural Gas` -> `WAGs PEFA MAL` -> `Pelletizing Malerij`.

| Link | bus0 | bus1 | Efficiency |
|---|---|---|---:|
| `Link_BOFG_to_Fuel_PEFA_Malerij` | `Bus_BOFG` | `Bus_Fuel_PEFA_Malerij` | `1.0` |
| `Link_NG_to_Fuel_PEFA_Malerij` | `Bus_NaturalGas` | `Bus_Fuel_PEFA_Malerij` | `1.0` |

Demand form:

```text
Fuel_PEFA_MAL[t] = PEFA_activity[t] * alpha_fuel_PEFA_MAL
```

Status:

- `alpha_fuel_PEFA_MAL` is redacted or unavailable.
- Do not activate as price-responsive unless reviewed.

### 12.3 Pelletizing Plant Branderij fuel

Athanasiadis controller: `COG` or `Natural Gas` -> `WAGs PEFA BRAND` -> `Pelletizing Branderij`.

| Link | bus0 | bus1 | Efficiency |
|---|---|---|---:|
| `Link_COG_to_Fuel_PEFA_Branderij` | `Bus_COG` | `Bus_Fuel_PEFA_Branderij` | `1.0` |
| `Link_NG_to_Fuel_PEFA_Branderij` | `Bus_NaturalGas` | `Bus_Fuel_PEFA_Branderij` | `1.0` |

Demand form:

```text
Fuel_PEFA_BRAND[t] = PEFA_activity[t] * alpha_fuel_PEFA_BRAND
```

Status:

- `alpha_fuel_PEFA_BRAND` is redacted or unavailable.
- Do not activate as price-responsive unless reviewed.

### 12.4 Main-plant fuel abstraction rule

For the first executable development model, use one of these two modes:

| Mode | Description | Recommended use |
|---|---|---|
| `fixed_process_linked` | Fuel demand is tied to process activity. Carrier split is fixed or bounded and price-insensitive. | base mode |
| `bounded_substitution` | WAG and NG can substitute within source-backed bounds. NG has external cost; WAG has no direct value. | later sensitivity |

Forbidden in base:

- arbitrary WAG-to-NG switching driven by electricity price;
- unrestricted plant-specific gas mixing;
- Wobbe-index optimisation;
- endogenous creation of WAG value through hidden opportunity prices.

---

## 13. Steam and boiler subsystem

### 13.1 Athanasiadis reference

Athanasiadis represents boiler gas use through boiler-specific gas controllers. The named units include:

| Athanasiadis unit | Inputs shown/described | Output |
|---|---|---|
| `Boilers 15,16,23,24` | `BFG`, `COG`, `Natural Gas`; BFG operation requires NG support | `Steam` |
| `Boiler 41` | `BFG`, `Natural Gas`; no COG | `Steam` |
| `STEG11` | `BFG`, `Natural Gas`; NG gas turbine plus heat recovery | `Steam`, `Electricity` |
| `TG2` | `Steam` | `Electricity` |

Athanasiadis does not apply boiler ramp limits at one-hour resolution.

### 13.2 Selected abstraction

The base model uses one aggregated steam/boiler block:

1. gas-specific Links into `Bus_BoilerFuel`;
2. one aggregated boiler Link from `Bus_BoilerFuel` to `Bus_Steam`;
3. optional reporting-only steam-to-electricity proxy for TG2/STEG11 only after values are reviewed.

### 13.3 Boiler-fuel Links

| Link | bus0 | bus1 | Efficiency | Base status |
|---|---|---|---:|---|
| `Link_BFG_to_BoilerFuel` | `Bus_BFG` | `Bus_BoilerFuel` | `1.0` | active |
| `Link_COG_to_BoilerFuel` | `Bus_COG` | `Bus_BoilerFuel` | `1.0` | active |
| `Link_NG_to_BoilerFuel` | `Bus_NaturalGas` | `Bus_BoilerFuel` | `1.0` | active |
| `Link_BOFG_to_BoilerFuel` | `Bus_BOFG` | `Bus_BoilerFuel` | `1.0` | deferred/ambiguous |

BOFG-to-boiler rule:

- Athanasiadis text says site heat demand is met by boilers using `COG`, `BOFG`, `BFG`, and `NG`.
- The rendered boiler figure emphasises `BFG`, `COG`, and `NG` for the boiler subsystem.
- Therefore `BOFG_to_BoilerFuel` remains **deferred or sensitivity-only** until the evidence is reconciled.

### 13.4 Aggregated boiler Link

| Link | bus0 | bus1 | Efficiency | Base candidate |
|---|---|---|---:|---:|
| `Link_AggregatedBoilers_to_Steam` | `Bus_BoilerFuel` | `Bus_Steam` | `eta_boiler_steam` | `0.90` |

Safe assumption:

- Use `Bus_Steam` in `MWh_th/h` to avoid unsupported tonne-steam enthalpy assumptions.
- Development-only boiler efficiency: `eta_boiler_steam = 0.90 MWh_th/MWh_LHV`.
- Sensitivity: `0.85-0.95`.

### 13.5 Steam demand

Steam demand is process-linked plus residual:

```text
SteamDemand[t] = SteamResidual[t] + sum_p(alpha_steam_p * activity_p[t])
SteamProduction[t] = SteamDemand[t] + Steam_to_TG2_or_STEG11[t]
```

Base rule:

- `Steam_to_TG2_or_STEG11[t] = 0` unless a reporting/sensitivity mode is explicitly activated.
- Steam has no internal price.
- Boiler NG cost enters only through `Generator_NaturalGasMarket`.

Development-only aggregate placeholder:

- Existing project notes mention a provisional `6 PJ/y` combined boiler/steam utility sink with an internal `3 PJ/y NG + 3 PJ/y WAG` allocation placeholder in one S3.3j development context.
- Treat this only as a development placeholder or reconciliation anchor, not as approved thesis truth.
- If used, convert to average power carefully:

```text
6 PJ/y = 1.6667 TWh/y = 190.26 MW average thermal/fuel-equivalent depending on definition
3 PJ/y = 0.8333 TWh/y = 95.13 MW average
```

This value must not be used silently as a plant capacity, connection capacity, or exact Tata steam demand.

### 13.6 Missing boiler/steam inputs

| Parameter | Status |
|---|---|
| `eta_boiler_steam` | development assumption only unless sourced |
| `p_nom_AggregatedBoilers` | redacted/unavailable |
| boiler minimum stable load | redacted/unavailable |
| BFG+NG co-firing ratio for boilers 15/16/23/24 | redacted/unavailable |
| Boiler 41 BFG minimum operation level | redacted/unavailable |
| STEG11 mandatory NG turbine consumption | redacted/unavailable |
| `eta_TG2` steam-to-electricity | redacted/unavailable |
| pressure-level split of steam network | not represented in base |
| process-specific steam coefficients | redacted/unavailable |
| residual steam load | redacted/unavailable |

---

## 14. Vattenfall / WAG electricity interface

### 14.1 Athanasiadis reference

Athanasiadis includes three nearby Vattenfall generators:

| Generator | Role in Athanasiadis |
|---|---|
| `IJ01` / `IJmond01` | normal WAG electricity generator |
| `VN25` / `Velsen Noord 25` | normal WAG electricity generator |
| `VN24` / `Velsen-Noord 24` | backup generator, not normal operation |

Public values/claims visible from Athanasiadis:

- combined capacity around `1 GW`;
- `VN24` is backup;
- `IJ01` and `VN25` run depending on gas availability, electricity prices, and Tata-Vattenfall contracts;
- contract details, emissions responsibility, profit allocation, and minimum gas-delivery obligations are not investigated;
- in one outage scenario, `VN25` is described with nominal capacity `600,000 m3 WAGs` and `350 MW` generation.

### 14.2 Selected abstraction

The base model treats Vattenfall as a **bounded interface sink**, not a dispatchable merchant generator.

Base rules:

- `Vattenfall` can absorb WAGs up to a cap if the interface mode is active.
- Vattenfall creates no DA revenue in the objective.
- Natural gas-to-Vattenfall is disabled in base.
- No Tata-Vattenfall contract is modelled.
- Electricity produced from WAGs is reporting-only unless a future net-import policy is explicitly approved.

### 14.3 Interface Links

| Link | bus0 | bus1 | Efficiency | Base status |
|---|---|---|---:|---|
| `Link_BFG_to_VattenfallFuel` | `Bus_BFG` | `Bus_VattenfallFuel` | `1.0` | active if interface enabled |
| `Link_COG_to_VattenfallFuel` | `Bus_COG` | `Bus_VattenfallFuel` | `1.0` | active if interface enabled |
| `Link_BOFG_to_VattenfallFuel` | `Bus_BOFG` | `Bus_VattenfallFuel` | `1.0` | active if interface enabled |
| `Link_NG_to_VattenfallFuel` | `Bus_NaturalGas` | `Bus_VattenfallFuel` | disabled | forbidden base |
| `Link_VattenfallFuel_to_ElectricityReporting` | `Bus_VattenfallFuel` | `Bus_ElectricityFromWAG_reporting` | `eta_Vattenfall` | reporting only |
| `Link_VattenfallFuel_to_ElectricityOffset` | `Bus_VattenfallFuel` | `Bus_Electricity` | `eta_Vattenfall` | deferred |

Missing values:

| Parameter | Status |
|---|---|
| `eta_Vattenfall` | redacted/unavailable |
| `p_nom_IJ01` | redacted/unavailable |
| `p_nom_VN25` | only partial public outage example: `600,000 m3 WAGs`, `350 MW`; not base executable without review |
| `p_nom_VN24` | redacted/unavailable |
| Tata-Vattenfall contract rules | unavailable |
| emissions boundary for Vattenfall combustion | unavailable |
| minimum WAG-delivery obligation | unavailable |
| electricity export revenue / settlement convention | unavailable and forbidden in base |

### 14.4 Optional generator gas-quality diagnostic

If volumetric gas flows are retained, compute reporting-only mixture LHV:

```text
LHV_mix[t] = (
    3.85 * V_BFG[t]
  + 8.6  * V_BOFG[t]
  + 18.5 * V_COG[t]
  + 37.5 * V_NG[t]
) / (V_BFG[t] + V_BOFG[t] + V_COG[t] + V_NG[t])
```

Athanasiadis-compatible generator-quality check:

```text
3.85 <= LHV_mix[t] <= 5.0 MJ/Nm3
```

Linear form:

```text
sum_g LHV_g * V_g[t] >= 3.85 * sum_g V_g[t]
sum_g LHV_g * V_g[t] <= 5.00 * sum_g V_g[t]
```

Base rule:

- Do not activate this as a binding constraint unless volumetric flows and Vattenfall mixing eligibility are reviewed.
- In the base energy-normalised model, report it only if volumes are available.

---

## 15. Flaring

### 15.1 Flaring Links

| Link | bus0 | bus1 | Emission factor | Status |
|---|---|---:|---:|---|
| `Link_Flare_BFG` | `Bus_BFG` | `Bus_CO2` | `EF_flare_BFG` | active |
| `Link_Flare_COG` | `Bus_COG` | `Bus_CO2` | `EF_flare_COG` | active |
| `Link_Flare_BOFG` | `Bus_BOFG` | `Bus_CO2` | `EF_flare_BOFG` | active |

Flaring prevents infeasibility when WAG production exceeds process, steam/boiler, and interface absorption. It must be reported by gas and by hour.

### 15.2 Flaring emissions

```text
CO2_flare[t] =
    EF_flare_BFG  * Flare_BFG[t]
  + EF_flare_COG  * Flare_COG[t]
  + EF_flare_BOFG * Flare_BOFG[t]
```

Emission factors are not currently source-approved. Options:

- reporting-only until factors are sourced;
- generic combustion factors as development assumptions;
- sensitivity-only ETS cost.

### 15.3 Flaring penalty

Base economic treatment:

- If CO2 objective terms are not active, use either no economic penalty or a small tie-breaker penalty only for deterministic allocation.
- Recommended development tie-breaker: `1-5 EUR/MWh_LHV flared`, labelled `non-economic flaring deterrence / tie-breaker`.
- Do not report this as a real Tata flaring cost.
- Do not double-count if ETS or combustion emissions costs are active.

---

## 16. Gas allocation hierarchy and degree-of-freedom restrictions

The central abstraction is **process-first, bounded utility, interface-next, flare residual**.

### 16.1 Base priority order

1. Mandatory direct process-linked fuel demand:
   - Sinter Plant COG;
   - KGF1 WAG/COG underfiring;
   - KGF2 COG underfiring in C0 only;
   - any approved BF/BOF/hot-stove route fuel demand if later added.
2. Approved main-plant process-fuel demands:
   - HSM;
   - PEFA Malerij;
   - PEFA Branderij.
3. Steam/boiler demand:
   - aggregated `Bus_BoilerFuel` -> `Bus_Steam`.
4. Vattenfall/interface sink:
   - capped, no revenue, no dispatch-plant claim.
5. Flaring:
   - residual balancing sink.

### 16.2 What the optimiser may decide in base

Allowed:

- process-unit activity within approved material-flow constraints;
- WAG production as a consequence of process activity;
- NG import where an approved gas or steam demand cannot be met by WAGs;
- WAG allocation within explicit eligibility and caps;
- flaring as a residual.

Restricted:

- WAG routing must not respond directly to DA electricity price unless the effect comes through approved process activity or approved external-cost substitution.
- WAG cannot be sold.
- Vattenfall cannot create profit in the objective.
- NG cannot be burned for Vattenfall electricity in base.
- No WAG storage or hour-to-hour shifting.
- No boiler unit commitment or boiler-specific binaries.
- No Wobbe-index optimisation.

### 16.3 Practical LP implementation of hierarchy

Preferred implementation for early LP:

- hard equality demands for mandatory process and steam loads;
- gas eligibility matrix for each sink;
- `NG` allowed only where Athanasiadis or assumptions allow substitution;
- `NG` cost makes WAG naturally displace NG where eligible;
- Vattenfall has zero objective value and a cap;
- flaring has reporting and optional small tie-breaker penalty;
- all economic claims report whether flaring penalty was a real cost, ETS proxy, or tie-breaker.

Avoid binary priority logic unless absolutely necessary.

---

## 17. Hourly balance equations

All balances are per hour `t`.

### 17.1 BFG balance

```text
BFG_prod_BF6[t] + BFG_prod_BF7[t]
= BFG_to_KGF1[t]
+ BFG_to_BoilerFuel[t]
+ BFG_to_VattenfallFuel[t]
+ BFG_flared[t]
+ BFG_to_other_approved_sinks[t]
```

C1 rule:

```text
BFG_prod_BF7[t] = 0
```

### 17.2 COG balance

```text
COG_prod_KGF1[t] + COG_prod_KGF2[t]
= COG_to_Sinter[t]
+ COG_to_KGF1[t]
+ COG_to_KGF2[t]
+ COG_to_HSM[t]
+ COG_to_PEFA_Branderij[t]
+ COG_to_BoilerFuel[t]
+ COG_to_VattenfallFuel[t]
+ COG_flared[t]
+ COG_to_other_approved_sinks[t]
```

C1 rules:

```text
COG_prod_KGF2[t] = 0
COG_to_KGF2[t] = 0
```

### 17.3 BOFG balance

```text
BOFG_prod_BOF[t]
= BOFG_to_PEFA_Malerij[t]
+ BOFG_to_VattenfallFuel[t]
+ BOFG_to_BoilerFuel[t]   # only if activated
+ BOFG_flared[t]
+ BOFG_to_other_approved_sinks[t]
```

Base rule:

```text
BOFG_to_BoilerFuel[t] = 0 unless BOFG boiler eligibility is reviewed and activated
```

### 17.4 Natural-gas balance

```text
NG_import[t]
= NG_to_HSM[t]
+ NG_to_PEFA_Malerij[t]
+ NG_to_PEFA_Branderij[t]
+ NG_to_BoilerFuel[t]
+ NG_to_DRP[t]
+ NG_residual_load[t]
+ NG_to_other_approved_sinks[t]
```

Base rule:

```text
NG_to_VattenfallFuel[t] = 0
```

### 17.5 Boiler and steam balances

```text
BoilerFuel[t]
= BFG_to_BoilerFuel[t]
+ COG_to_BoilerFuel[t]
+ NG_to_BoilerFuel[t]
+ BOFG_to_BoilerFuel[t]

SteamProduction[t] = eta_boiler_steam * BoilerFuel[t]

SteamProduction[t]
= SteamResidual[t]
+ sum_p(alpha_steam_p * activity_p[t])
+ Steam_to_TG2_or_STEG11[t]
```

Base rule:

```text
Steam_to_TG2_or_STEG11[t] = 0
```

---

## 18. Economic representation

### 18.1 Base objective

The base objective remains fixed-production cost minimisation:

```text
min sum_t [
    lambda_DA[t] * GridImport[t]
  + c_NG[t]      * NG_import[t]
  + c_raw[t]     * RawMaterialUse[t]
  + c_CO2[t]     * CO2[t]              # only if carbon policy is explicit
  + penalty_shortfall * Shortfall[t]
  + optional_flare_tiebreaker * FlaredEnergy[t]
]
```

Active terms depend on stage readiness.

### 18.2 WAG marginal cost

```text
c_BFG = 0
c_COG = 0
c_BOFG = 0
```

Interpretation:

- WAGs are by-products of steel process operation.
- Upstream costs are already counted through raw materials, process activity, and emissions.
- Zero WAG marginal cost avoids double counting.
- It does not mean WAGs have unlimited economic value.

### 18.3 No direct WAG revenue

Forbidden in the base model:

```text
- lambda_DA[t] * ElectricityFromWAG[t]
```

unless a future, reviewed Vattenfall/net-import contract boundary is explicitly activated.

Athanasiadis includes WAG-to-electricity revenue through negative marginal cost on WAG generation Links. This thesis model does **not** use that in the base case because the Tata-Vattenfall contract, emissions boundary, dispatch control, and minimum gas-delivery obligations are not public.

### 18.4 Steam economics

- No internal steam price.
- Steam cost enters only through boiler fuel, mainly NG import where explicitly modelled.
- WAG use for steam has no artificial internal opportunity cost.

### 18.5 Carbon economics

- CO2 is tracked physically.
- ETS or carbon price may be reporting-only or sensitivity-only until boundary and free-allocation treatment are explicit.
- Flaring emissions must not be hidden.
- Free allocation is not netted silently.

---

## 19. Recommended safe assumptions for missing values

These are **development-only** unless promoted through the source-to-input workflow.

| Parameter | Base development value | Sensitivity | Status |
|---|---:|---:|---|
| `alpha_BFG_BF` | `1500 Nm3/t HM` = `1.604 MWh/t HM` | `1300-1800 Nm3/t HM` | `development_assumption` |
| `alpha_COG_KGF` | `350 Nm3/t coke` = `1.799 MWh/t coke` | `300-400 Nm3/t coke` | `development_assumption` |
| `alpha_BOFG_BOF` | `80 Nm3/t BOF steel` = `0.191 MWh/t` | `50-120 Nm3/t`, plus `0` recovery | `development_assumption` |
| `eta_boiler_steam` | `0.90 MWh_th/MWh_LHV` | `0.85-0.95` | `development_assumption` |
| `alpha_fuel_KGF` | `3.5 GJ/t coke` = `0.972 MWh/t coke` | `3.0-4.0 GJ/t coke` | `development_assumption` |
| `alpha_fuel_Sinter_COG` | `0.10 GJ/t sinter` = `0.0278 MWh/t sinter` | `0`, `0.05`, `0.15`, `0.25 GJ/t` | `development_assumption` |
| `p_flare_tiebreaker` | `1-5 EUR/MWh_LHV flared` | `0`, `1`, `5`, carbon-only | `sensitivity_only` |
| Vattenfall objective value | `0 EUR/MWh` | no-revenue base; optional reporting only | `frozen_for_phase` |
| WAG storage capacity | `0` | no base sensitivity unless sub-hour model exists | `frozen_for_phase` |
| Steam storage capacity | `0` | only if sourced | `frozen_for_phase` |

Safe-assumption interpretation:

- These values are conservative placeholders for development and stress testing.
- They should never be written as “Tata values”.
- Sensitivity must test whether WAG availability materially changes route cost, NG exposure, flaring, or apparent flexibility.

---

## 20. Missing values that must stay visible

| Category | Missing value | Base treatment |
|---|---|---|
| WAG production | `alpha_COG_KGF1`, `alpha_COG_KGF2`, `alpha_BFG_BF6`, `alpha_BFG_BF7`, `alpha_BOFG_BOF` | development assumptions + sensitivity |
| Process fuel | `alpha_fuel_Sinter`, `alpha_fuel_KGF1`, `alpha_fuel_KGF2`, `alpha_fuel_HSM`, `alpha_fuel_PEFA_MAL`, `alpha_fuel_PEFA_BRAND` | mandatory sinks where minimal values exist; otherwise blocked/aggregate |
| Steam | `alpha_steam_p`, residual steam load, pressure-level split | aggregate placeholder or blocked |
| Boilers | capacity, min load, efficiency, BFG+NG co-firing ratios, Boiler 41 rules, STEG11 rules | aggregated boiler block |
| Vattenfall | generator capacities, efficiency, contracts, emissions responsibility, minimum WAG supply | interface only, no revenue |
| Flaring | gas-specific combustion factors and true penalty/cost | reporting or development tie-breaker |
| Carbon | ETS boundary, free allocation, Vattenfall emissions boundary | reporting/sensitivity only until explicit |
| Natural gas price | hourly/monthly price convention | fixed or time-series external cost if reviewed |
| Residual loads | residual electricity, NG, steam, CO2 time series | residual Loads only if source/review exists |

---

## 21. Model input-table mapping

The gas-network abstraction should map to the existing S4.4 input contract.

| Table | Rows to add or check |
|---|---|
| `configuration_assets.csv` | C0/C1 active status for `BF6`, `BF7`, `KGF1`, `KGF2`, `BOF`, Sinter, PEFA, HSM, boilers, Vattenfall interface. |
| `process_units.csv` | process Link definitions and activity bases. |
| `process_io_coefficients.csv` | material and utility coefficients, including process-linked COG/WAG demand. |
| `process_energy_intensities.csv` | electricity, NG, steam, WAG/fuel intensities where approved. |
| `process_emission_factors.csv` | process and combustion factors. |
| `buffers_and_stores.csv` | no WAG Stores; no Steam Store; CO2 accumulator only. |
| `wag_generation_coefficients.csv` | `alpha_BFG`, `alpha_COG`, `alpha_BOFG` with basis and status. |
| `wag_sink_eligibility.csv` | allowed gas/sink pairs, including direct process sinks and boiler/interface/flare sinks. |
| `utility_demands.csv` | steam demand, boiler utility sink, residual steam/NG/electricity if active. |
| `utility_conversion_assets.csv` | aggregated boiler, Vattenfall interface, optional TG2/STEG11 reporting rows. |
| `external_supply_costs.csv` | NG, electricity, raw material, CO2 if active. |
| `market_price_inputs.csv` | DA electricity prices only for market stages. |
| `policy_modes.csv` | no WAG revenue, Vattenfall interface, no WAG storage, no steam store, CO2 reporting/sensitivity. |
| `solver_and_horizon_config.csv` | hourly base; no quarter-hour until later gate. |

Every row must include source/governance fields:

```text
source_card_ids, candidate_id, evidence_strength, input_status,
thesis_usability, codex_may_decide, human_review_required, caveat
```

---

## 22. Validation and reporting requirements

Every run that includes this layer must report at least:

### 22.1 Balance diagnostics

- hourly `BFG` production, use, interface, flare, balance residual;
- hourly `COG` production, use, interface, flare, balance residual;
- hourly `BOFG` production, use, interface, flare, balance residual;
- hourly `NG` import and use by sink;
- hourly steam production, demand, and residual;
- flared energy by gas and total;
- CO2 from process, combustion, residual, and flaring where active.

### 22.2 Operational diagnostics

- C0/C1 active asset status;
- BF7 and KGF2 exactly zero in C1;
- Sinter COG demand included if Sinter active;
- CP2 COG demand included in C0 and zero in C1;
- KGF1 fuel demand included in both C0 and C1 if KGF1 active;
- WAG storage variables absent or fixed to zero;
- Vattenfall interface use and cap hits;
- boiler/steam demand fulfilment;
- flaring periods and volumes.

### 22.3 Economic diagnostics

- NG cost;
- electricity cost if active;
- raw-material costs if active;
- CO2 reporting/cost if active;
- flare tie-breaker cost separately labelled;
- no WAG revenue in base;
- no product revenue in base;
- EUR/t final product only after production fulfilment is confirmed.

### 22.4 Sensitivity diagnostics

At minimum, test:

- low/base/high BFG production;
- low/base/high COG production;
- BOFG recovery on/off or low/base/high;
- boiler efficiency;
- coking underfiring demand;
- Sinter COG demand;
- Vattenfall interface disabled/capped/high-cap;
- flaring penalty zero versus small tie-breaker;
- carbon reporting-only versus carbon sensitivity if relevant.

---

## 23. Red flags

A result using this layer is not thesis-usable if any of the following occur:

- WAGs are monetised directly as DA revenue in the base case.
- Vattenfall is treated as a Tata-controlled merchant generator without contract evidence.
- NG is allowed to create electricity revenue through Vattenfall.
- Sinter Plant COG demand is omitted while claiming full COG balance.
- CP2 COG demand is active in C1 after CP2/KGF2 shutdown.
- BF7 or KGF2 produces gas in C1.
- WAG storage or steam storage creates hidden intertemporal flexibility.
- BOFG boiler use is activated without resolving the evidence ambiguity.
- Flaring is hidden or treated as free without reporting.
- CO2 or ETS costs steer dispatch without an explicit boundary and free-allocation convention.
- Candidate or workbook-only values are used as executable values without migration and review.
- Forecast-quality comparisons change WAG hierarchy, production policy, or economic boundary at the same time as forecast/scenario input.

---

## 24. Final base representation in one paragraph

The WAG/steam/gas layer represents `BFG`, `COG`, and `BOFG` as separate hourly `Bus` balances produced by the active steel-process `Links` (`BF6`, `BF7`, `KGF1`, `KGF2`, `BOF`) and consumed by direct process-fuel sinks (`Sinter`, `KGF1`, `KGF2`), approved main-plant fuel sinks (`HSM`, `PEFA Malerij`, `PEFA Branderij`), an aggregated boiler-fuel-to-steam block, a capped Vattenfall/interface sink, or gas-specific flaring Links. `C1` disables both `BF7` and `KGF2 / Coking Plant 2`, so their WAG production and direct COG consumption are zero. Natural gas is an external `Generator` used only where explicit process, DRP, residual, or boiler demand allows it. No WAG or steam Stores exist at hourly resolution. Vattenfall has no base objective revenue. Flaring is explicit and reported. Economics include only reviewed external costs and labelled reporting/sensitivity terms, preserving physical accounting without creating fake internal-energy flexibility.

---

## 25. Suggested assumption-register rows

| Assumption ID | Statement | Status | Sensitivity |
|---|---|---|---|
| `A_WAG_NO_STORAGE_HOURLY_001` | WAG carriers have no Store components at hourly resolution; each gas bus balances within the hour. | `frozen_for_phase` | none unless sub-hour model |
| `A_STEAM_BUS_NO_STORE_001` | Steam is represented as a Bus with no Store unless finite capacity and terminal policy are sourced. | `frozen_for_phase` | recommended only if evidence appears |
| `A_WAG_PROCESS_FIRST_001` | WAG allocation follows process-first, boiler/steam-next, interface-next, flare-residual logic. | `frozen_for_phase` | required |
| `A_WAG_DIRECT_PROCESS_SINKS_001` | Sinter COG use and Coking Plant 1/2 underfiring are included as process-linked sinks; CP2 sink is inactive in C1. | `frozen_for_phase` | required |
| `A_VATTENFALL_INTERFACE_NO_REVENUE_001` | Vattenfall is a capped interface/reporting sink, not a merchant generator in the base objective. | `frozen_for_phase` | required |
| `A_BOILER_AGGREGATION_001` | Boilers 15/16/23/24, Boiler 41, STEG11, and TG2 are represented by an aggregated boiler/steam block in base. | `frozen_for_phase` | required |
| `A_BOFG_BOILER_DEFER_001` | BOFG-to-boiler use remains deferred/sensitivity-only until the public text/figure ambiguity is resolved. | `provisional` | required |
| `A_WAG_DEV_COEFFICIENTS_001` | Generic BFG/COG/BOFG coefficients may be used for development only with sensitivity bounds. | `provisional` | required |
| `A_FLARE_TIEBREAKER_001` | A small flaring penalty may be used only as a labelled tie-breaker unless CO2/ETS costs are explicit. | `provisional` | required |
