# Blast_Furnace_Parameters.md

**Path:** `data/03_Optimisation/inputs/assets/steel/source_cards/Blast_Furnace_Parameters.md`
**Scope:** Tata Steel IJmuiden-inspired BF6/BF7, BFG generation, BF hot-stove WAG use and BF carbon-accounting convention.
**Status:** candidate parameter note and development-assumption surface; not thesis-approved and not an approved executable input table.
**Last updated:** 2026-06-30.
**Main use:** source-backed and assumption-backed BF6/BF7 parameterisation for the S4.4c plant-by-plant physical/accounting model.

## 1. Core modelling conclusion

For the base public Tata-inspired C0/C1 steel model, BF6 and BF7 should be represented as continuous, production-coupled process links rather than hourly day-ahead price-responsive flexibility assets.

The blast-furnace process link remains simple and must not directly consume WAGs, BFG, COG, BOFG, natural gas, or a generic mixed-gas carrier as a BF reactor input:

```text
coke + sinter + pellets/ore + PCI coal + oxygen + electricity + steam
  -> BF6 / BF7 process link
  -> hot metal + BFG + slag + CO2 accounting output
```

The blast-furnace route also requires hot-blast heat. This should not be represented as free direct WAG injection into the BF reactor. It should be represented as a separate **`Controller_Blast_Furnace` / BF hot-stove / blast-heating controller**:

```text
eligible clean BFG + clean COG + clean BOFG + Natural_Gas
  -> Controller_Blast_Furnace
  -> WAGs_BF_Hot_Stove / BF_hot_stove_heat
  -> BF hot-stove / hot-blast heat demand
```

This follows the same Athanasiadis-style plant gas-controller pattern used for controllers such as `Controller Hot Strip Mill`, `Controller Coking Plant 1`, `Controller PEFA Malerij`, and `Controller PEFA Branderij`: eligible gases enter a controller/mixing structure, the controller creates a plant-specific WAG or heat carrier, and that carrier satisfies the plant demand. The explicit BF hot-stove controller prevents all BF-generated BFG from being treated as freely available surplus.

The first implementation should be energy-basis and accounting-oriented:

```text
BF_hot_stove_heat_demand = hot_metal_BF * 2.20 GJ/t HM
```

No volume/LHV gas-quality constraint is required in the first implementation. A volume-based mixed-gas constraint can be added later as a sensitivity.

## 2. Project-baseline values that must not be silently overridden

Some source ranges in this note differ from values already used in the C5-series model diagnostics. In S4.4c5h, the existing project baseline controls unless a later explicit migration decision changes it.

| Parameter                              | Base value to use now | Unit         | Reason                                                                                                |
| -------------------------------------- | --------------------: | ------------ | ----------------------------------------------------------------------------------------------------- |
| `BFG_LHV_MJ_PER_NM3`                   |              **3.85** | MJ/Nm³       | Already used as canonical BFG conversion in the WAG diagnostics. Do not replace with 3.3 in the base. |
| `COG_LHV_MJ_PER_NM3`                   |              **18.5** | MJ/Nm³       | Already used in KGF/COG diagnostics.                                                                  |
| `BOFG_LHV_MJ_PER_NM3`                  |               **8.6** | MJ/Nm³       | Already used in BOFG diagnostics.                                                                     |
| `BF_BFG_OUTPUT_NM3_PER_T_HM`           |              **1600** | Nm³/t HM     | Existing C5 diagnostics basis.                                                                        |
| `BF_BFG_OUTPUT_MWH_PER_T_HM`           |          **1.711111** | MWh_LHV/t HM | Derived from `1600 * 3.85 / 3600`.                                                                    |
| `BF_BFG_OUTPUT_GJ_PER_T_HM`            |              **6.16** | GJ_LHV/t HM  | Derived from the canonical 1600 Nm³/t and 3.85 MJ/Nm³.                                                |
| `BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM` |              **2.20** | GJ/t HM      | New development assumption from BF note; not yet site-approved.                                       |
| `BF_CO2_COUNTER_AGG_T_PER_T_HM`        |             **1.495** | tCO2e/t HM   | Development aggregate hot-metal counter for first compact BF CO2 implementation.                      |

Conflicting or alternative values remain useful for sensitivity, but should not become base inputs silently. In particular:

| Conflicting value                | Status                                                                                                                                                   |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BFG_LHV = 3.3 MJ/Nm³`           | Retire from base. Use only as gas-quality/mixed-gas sensitivity if volume-based hot-stove constraints are opened.                                        |
| `BF_BFG_OUTPUT = 4.72 GJ/t HM`   | Retain as candidate/sensitivity or conflict row. Do not use together with `1600 Nm³/t HM` and `3.85 MJ/Nm³`.                                             |
| `COG_LHV = 18.0 MJ/Nm³`          | Retire from base because KGF diagnostics use 18.5 MJ/Nm³.                                                                                                |
| `BOFG_LHV = 9.58 MJ/Nm³`         | Retire from base because current BOFG diagnostics use 8.6 MJ/Nm³.                                                                                        |
| `BF_SINTER_INPUT = 1.088 t/t HM` | Candidate value only. Current executable model has a lower inherited sinter ratio; changing this requires an explicit BF/Sinter reconciliation decision. |

## 3. Source hierarchy

| Rank | Source                                                                                                                     | Use                                                                                                                                        |
| ---: | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
|    1 | Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025), *MER Heracless - Groen Staal, Deel B: Technische beschrijving* | Public Tata-specific topology: HO6/HO7, HO7 closure, hot blast, BFG capture/cleaning/use, Heracless annual production context.             |
|    2 | Remus et al. (2013), *JRC Iron and Steel BREF*                                                                             | Generic EU BF coefficients and ranges for coke rate, burden mix, PCI, oxygen, electricity, steam, BFG generation and hot-stove fuel logic. |
|    3 | European Commission DG Climate Action (2021), ETS benchmark factsheets                                                     | Hot-metal CO2e benchmark/counter values for aggregate CO2 reporting and ETS benchmark comparison.                                          |
|    4 | Koolen, Vidovic & Somers (2022), JRC                                                                                       | Waste-gas attribution and BFG carbon-accounting caution.                                                                                   |
|    5 | Athanasiadis (2025), MSc thesis                                                                                            | PyPSA-style process links, BF6/BF7 modelling precedent and gas-network/mixing-controller architecture.                                     |
|    6 | S4.4b2 Physical Master Workbook / project governance                                                                       | Separate BFG/COG/BOFG carriers, no direct WAG market valuation, C1 as change set over C0, BF7 inactive and BF6 retained.                   |

## 4. Topology and annual validation anchors

These values are validation/context anchors, not hourly dispatch constraints.

| Parameter ID                | Base / anchor | Unit    | Model use      | Status                    |
| --------------------------- | ------------: | ------- | -------------- | ------------------------- |
| `BF_C0_ACTIVE_UNITS`        |     BF6 + BF7 | -       | C0 topology    | source-backed topology    |
| `BF_C1_ACTIVE_UNITS`        |      BF6 only | -       | C1 topology    | source-backed topology    |
| `BF6_HM_REF_ANNUAL_MT`      |           2.5 | Mt HM/y | C0 validation  | validation anchor         |
| `BF7_HM_REF_ANNUAL_MT`      |           3.8 | Mt HM/y | C0 validation  | validation anchor         |
| `BF_TOTAL_HM_REF_ANNUAL_MT` |           6.3 | Mt HM/y | C0 validation  | derived validation anchor |
| `BF6_HM_C1_ANNUAL_MT`       |           2.8 | Mt HM/y | C1 validation  | validation anchor         |
| `BF6_HM_C1_LOW_SENS_MT`     |           2.2 | Mt HM/y | C1 sensitivity | sensitivity-only          |
| `BF7_HM_C1_ANNUAL_MT`       |             0 | Mt HM/y | C1 topology    | source-backed topology    |

The Heracless annual values may be used to check whether the bottom-up model is plausible. They must not force optimiser outputs.

## 5. Minimal BF process parameters

The first BF parameterisation should only implement the minimum set needed for material, WAG, electricity, steam and CO2 diagnostics.

| Parameter ID                     |                          Base |    Low |   High | Unit                | Status                                           |
| -------------------------------- | ----------------------------: | -----: | -----: | ------------------- | ------------------------------------------------ |
| `BF_COKE_RATE_T_PER_T_HM`        |                         0.359 |  0.282 |  0.515 | t coke/t HM         | source-backed development assumption             |
| `BF_HM_PER_T_COKE`               |                         2.786 |  1.942 |  3.546 | t HM/t coke         | derived                                          |
| `BF_PCI_COAL_INPUT_T_PER_T_HM`   |                         0.162 |      0 |  0.232 | t PCI coal/t HM     | source-backed development assumption             |
| `BF_OXYGEN_INPUT_KG_PER_T_HM`    |                          54.4 |      0 |   85.1 | kg O2/t HM          | source-backed development assumption             |
| `BF_ELECTRICITY_MWH_PER_T_HM`    |                        0.0744 | 0.0297 |  0.236 | MWh/t HM            | source-backed development assumption             |
| `BF_STEAM_GJ_PER_T_HM`           |                         0.048 |      0 |   open | GJ steam proxy/t HM | source-backed development assumption             |
| `BF_SLAG_T_PER_T_HM`             |               diagnostic only |  0.150 | 0.3466 | t slag/t HM         | diagnostic/sensitivity                           |
| `BF_SINTER_INPUT_T_PER_T_HM`     | keep current executable value |   open |   open | t sinter/t HM       | do not override without BF/Sinter reconciliation |
| `BF_PELLET_INPUT_T_PER_T_HM`     |                      deferred |      0 |  0.972 | t pellets/t HM      | later burden-mix reconciliation                  |
| `BF_DIRECT_ORE_INPUT_T_PER_T_HM` |                      deferred |      0 |  0.684 | t ore/t HM          | optional later                                   |

The BF coke rate is new for the BF implementation and will likely expose a coke-balance gap against the KGF system. That gap should be reported, not hidden.

Gate-1 basis audit: the executable `2.1041666667 t hot metal/t represented
sinter` coefficient implies `0.4752475 t represented sinter/t hot metal`. Its
lineage is a controlled S4.4b5 development completion proxy rather than a
measured Tata burden recipe. It represents only the modelled sinter share and
does not silently include the deferred pellet or direct-ore rows. Coke remains
on its separate hot-metal balance, while PCI is not yet a closed material-flow
burden term. The higher `1.088 t sinter/t hot metal` source-card candidate is
therefore a visible unresolved full-burden reconciliation candidate, not an
automatic replacement for Gate 1.

## 6. BFG generation and surplus convention

Use the existing project WAG convention:

```text
BFG_volume_Nm3 = hot_metal_t * 1600
BFG_energy_MWh_LHV = BFG_volume_Nm3 * 3.85 / 3600
BFG_energy_GJ_LHV = BFG_energy_MWh_LHV * 3.6
```

Per tonne hot metal:

```text
BFG_output = 1600 Nm3/t HM
BFG_LHV = 3.85 MJ/Nm3
BFG_output = 1.711111 MWh_LHV/t HM
BFG_output = 6.16 GJ_LHV/t HM
```

Gross BFG is not automatically available as surplus to the general WAG network. BF hot-stove demand must be deducted first:

```text
gross_BFG_generated
  - BFG_to_BF_hot_stove
  = net_BFG_surplus_to_WAG_network
```

If BFG is insufficient for hot-stove heat, natural gas may supplement as a costed external backup. COG and BOFG may be allowed as enrichment gases only if explicitly enabled in the allocation logic. Raw or dirty gases are not normal fuel inputs.

## 7. BF hot-stove / WAG-controller convention

The first implementation is energy-only:

```text
BFG_to_BF_stove_MWh
+ BOFG_to_BF_stove_MWh
+ COG_to_BF_stove_MWh
+ NG_to_BF_stove_MWh
= BF_hot_stove_heat_demand_MWh
```

Demand driver:

```text
BF_hot_stove_heat_demand_MWh =
    hot_metal_BF_t * 2.20 / 3.6
```

Base allocation interpretation:

1. Use available BFG first.
2. Use BOFG or COG only if enabled and physically available.
3. Use NG only as external backup.
4. Report all hot-stove gas use separately.
5. Do not assign direct electricity-market value to WAG.

Volume/LHV-mix constraints are deferred. If later opened, use the canonical carrier LHVs already used elsewhere in the model:

```text
BFG  = 3.85 MJ/Nm3
COG  = 18.5 MJ/Nm3
BOFG = 8.6 MJ/Nm3
```

## 8. CO2 and carbon-accounting convention

The BF carbon convention must avoid double counting. Two modes are valid, but only one may be active in a given run.

### Mode A — aggregate hot-metal counter mode

This is the recommended first implementation.

```text
BF_CO2_from_hot_metal_t =
    hot_metal_BF_t * 1.495
```

In this mode:

* `BF_CO2_COUNTER_AGG_T_PER_T_HM = 1.495`;
* BFG downstream combustion CO2 is disabled or diagnostic-only;
* BFG carbon is not counted again at Vattenfall, boilers or flaring;
* this gives a compact BF/hot-metal CO2 counter;
* it is not exact Tata truth and not a pure BF-reactor chemistry coefficient.

### Mode B — WAG-explicit carbon mode

This is more transparent but requires all major BFG sinks to be represented consistently.

```text
CO2_from_BFG_combustion =
    BFG_energy_to_sink_TJ * 260 tCO2/TJ
```

In this mode:

* BFG is treated as a carbon-bearing energy carrier;
* CO2 is counted at combustion/flaring sinks;
* the aggregate BF CO2 counter is disabled;
* all BFG sinks must be represented, otherwise emissions will be incomplete.

### Base choice

For S4.4c5h, use:

```text
BF_CARBON_ACCOUNTING_MODE = aggregate_hot_metal_counter
BF_CO2_COUNTER_AGG_T_PER_T_HM = 1.495
BFG_DOWNSTREAM_COMBUSTION_CO2 = diagnostic_only
```

The WAG-explicit mode can be tested later after boiler, Vattenfall, hot-stove and flaring sinks are more complete.

## 9. Expected annual diagnostics

Indicative site-scale checks, not constraints:

| Configuration      |                 Hot metal basis |                                  Gross BFG | Hot-stove demand | Interpretation                                                                |
| ------------------ | ------------------------------: | -----------------------------------------: | ---------------: | ----------------------------------------------------------------------------- |
| C0                 | BF6 2.5 + BF7 3.8 = 6.3 Mt HM/y | 38.8 PJ/y using 1600 Nm³/t and 3.85 MJ/Nm³ |        13.9 PJ/y | Both BFs active. Hot-stove self-use should materially reduce net BFG surplus. |
| C1                 |     BF6 2.8 Mt HM/y, BF7 closed | 17.2 PJ/y using 1600 Nm³/t and 3.85 MJ/Nm³ |         6.2 PJ/y | BF7 closure strongly reduces gross BFG and BFG surplus.                       |
| C1 low sensitivity |     BF6 2.2 Mt HM/y, BF7 closed |                                  13.6 PJ/y |         4.8 PJ/y | Annual sensitivity only; not hourly flexibility.                              |

## 10. First implementation equations

If the solver remains hot-metal-output driven:

```text
coke_input_BF_i,t = hot_metal_BF_i,t * BF_COKE_RATE_T_PER_T_HM
PCI_BF_i,t        = hot_metal_BF_i,t * BF_PCI_COAL_INPUT_T_PER_T_HM
O2_BF_i,t         = hot_metal_BF_i,t * BF_OXYGEN_INPUT_KG_PER_T_HM
elec_BF_i,t       = hot_metal_BF_i,t * BF_ELECTRICITY_MWH_PER_T_HM
steam_BF_i,t      = hot_metal_BF_i,t * BF_STEAM_GJ_PER_T_HM / 3.6

BFG_gross_Nm3_i,t = hot_metal_BF_i,t * 1600
BFG_gross_MWh_i,t = BFG_gross_Nm3_i,t * 3.85 / 3600

hot_stove_MWh_i,t = hot_metal_BF_i,t * 2.20 / 3.6
```

If the solver is later migrated to coke-input `bus0`:

```text
hot_metal_BF_i,t = coke_input_BF_i,t / 0.359
```

Until that migration is complete, report:

```text
bus0_basis = hot_metal_basis_with_coke_equivalent_reporting
```

## 11. Required diagnostics

Every BF run should report:

* BF6/BF7 active status by configuration;
* hot metal produced;
* coke demand;
* KGF coke output versus BF coke demand;
* PCI coal use;
* oxygen use;
* electricity use;
* steam proxy;
* gross BFG generated;
* BFG to hot stove;
* net BFG surplus to WAG network;
* NG backup to hot stove, if any;
* aggregate BF CO2 counter;
* BFG carbon diagnostic-only if applicable;
* C0/C1 annual anchor gaps;
* WAG balance closure.

## 12. What should not be claimed

Do not claim that:

* the candidate coefficients are exact Tata BF6/BF7 operating recipes;
* BF6 and BF7 have different efficiency in the base case;
* hot-stove gas use is direct WAG injection into the BF reactor;
* the Heracless annual BF6 flexibility band is an hourly ramping limit;
* gross BFG is fully available as surplus before hot-stove demand is satisfied;
* WAG has direct day-ahead electricity-market value;
* BFG carbon is counted both at BF generation and again at combustion/flaring;
* the aggregate BF CO2 counter is exact Tata direct emissions.

Most defensible thesis wording:

> BF6 and BF7 are represented as continuous, production-coupled blast-furnace links. Public Tata/MER material supports the topology and Heracless closure logic, while generic technical literature and governed development assumptions provide candidate coefficients. BFG is represented as a separate WAG carrier, with hot-stove self-use deducted before surplus BFG enters the site WAG network. BF CO2 is initially represented with an aggregate hot-metal counter to avoid double-counting BFG carbon before a fully WAG-explicit carbon ledger is implemented.
