# Pelletizing Plant / PeFa Parameters — compact source-card memo

## Status

This note records a compact, source-backed candidate parameter set for the Tata Steel IJmuiden-inspired Pelletizing Plant (`PeFa`). It is a **candidate/source-card memo**, not an executable input table and not thesis-approved truth.

Rows below must be migrated through the normal workflow before model use:

`source -> source card -> candidate evidence -> assumption/register row -> reviewed development input -> executable model input`

## Scope and modelling intention

The Pelletizing Plant converts iron ore into fired pellets. For the first implementation the process is represented as a continuous upstream material-preparation process, not as a day-ahead flexibility asset.

Preferred basis:

```text
P_PEFA[t] = fired_pellets_output[t]      # t pellets/h
```

The plant is split conceptually into two subprocesses, following Athanasiadis' modelling structure:

1. **Malerij**: mixing / drying / grinding stage.
2. **Branderij**: firing / induration stage.

The split is used to keep the WAG controllers physically interpretable. The first executable implementation should still remain simple and avoid detailed kiln-zone or burner modelling.

## Source hierarchy

| Rank | Source | Main use | Reliability / caveat |
|---:|---|---|---|
| 1 | Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025), *MER Heracless - Groen Staal, Deel B: Technische beschrijving* | Tata-specific topology, C0/C1 production anchors, operational-flexibility band, pellet-use context, LoTOx/DeNOx context. | High for public Tata topology and annual anchors. Does not give full conversion factors. |
| 2 | Remus, R., Aguado-Monsonet, M. A., Roudier, S., & Delgado Sancho, L. (2013), *Best Available Techniques (BAT) Reference Document for Iron and Steel Production*, European Commission JRC, Chapter 4 Pelletisation | Generic but high-authority candidate values for iron ore input, electricity, COG/BOF gas, natural gas, coke breeze, waste gas and CO2 per t pellets; heat recovery in the Dutch pelletisation plant. | High technical authority, but not Tata-validated operating truth. Table 4.1 values are from EU plants and some entries are site/scope-specific. |
| 3 | Athanasiadis, I. (2025), *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site* | PyPSA modelling precedent for splitting Pelletizing Plant into Malerij and Branderij, and for WAG controller treatment. | Useful modelling precedent only; not an exact public Tata parameter source. |
| 4 | Project governance / S4.4 physical model policy | Ensures BFG, COG and BOFG remain separate carriers and WAG only exists after explicit mixing. | Governance only, not external evidence. |

## Compact process representation

```text
iron_ore + electricity + gas_fuel + solid_fuel -> fired_pellets + CO2
```

Optional controller representation:

```text
Malerij drying/grinding heat:     BOFG + NG -> PEFA_malerij_heat
Branderij induration/firing heat: COG  + NG -> PEFA_branderij_heat
```

The plant does **not** produce useful WAG. Pelletizing waste gas is an off-gas/emissions stream, not a reusable fuel carrier.

## WAG-controller implementation choice

### Option A — selected for first implementation

Use one total gas-heat requirement linked to pellet output, while preserving the two controller categories for accounting and future refinement.

```text
PEFA_gas_heat_demand[t] = P_PEFA[t] * PEFA_GAS_FUEL_TOTAL_GJ_PER_T

PEFA_malerij_heat[t] + PEFA_branderij_heat[t] = PEFA_gas_heat_demand[t]

PEFA_malerij_heat[t]    may be supplied by BOFG and/or NG
PEFA_branderij_heat[t]  may be supplied by COG and/or NG
```

Rationale:

- The public BREF gives total gas-energy values for the integrated Dutch pelletising context, but not a reliable split between Malerij and Branderij.
- Athanasiadis' split is structurally useful, but his public thesis should not be treated as an exact numerical input source.
- Option A prevents unallocated annual energy demand by assigning gas, electricity and solid-fuel intensities per t pellets, while avoiding an invented stage-energy split.

Caveat: if the optimiser exploits this freedom by routing all gas through the cheapest controller in a physically implausible way, move to Option B.

### Option B — later guardrail if needed

Introduce an explicit development-only stage split, for example:

```text
PEFA_MALERIJ_GAS_SHARE    = 0.35
PEFA_BRANDERIJ_GAS_SHARE  = 0.65
```

Then:

```text
PEFA_malerij_heat[t]   = P_PEFA[t] * PEFA_GAS_FUEL_TOTAL_GJ_PER_T * PEFA_MALERIJ_GAS_SHARE
PEFA_branderij_heat[t] = P_PEFA[t] * PEFA_GAS_FUEL_TOTAL_GJ_PER_T * PEFA_BRANDERIJ_GAS_SHARE
```

This split is **not source-backed**. It is only a modelling guardrail and must be labelled as a sensitivity/development assumption.

## Candidate parameter set

| Parameter ID | Unit | Range / value | Most likely / selected | Status | Source and locator | Model role and caveat |
|---|---:|---:|---:|---|---|---|
| `PEFA_OUTPUT_BASIS` | t pellets | fired pellets | fired pellets | modelling choice | MER Heracless §3.2.2; JRC BREF Ch.4 Table 4.1 | Primary activity basis. |
| `PEFA_C0_OUTPUT_ANNUAL_MT` | Mt/y | 4.6 | 4.6 | validation anchor | MER Heracless Table 5.1 / §13.2 | C0/reference annual output; anchor, not hourly cap. |
| `PEFA_C1_OUTPUT_ANNUAL_MT` | Mt/y | 5.0 | 5.0 | validation anchor | MER Heracless Table 5.1 / §13.2 | C1/Heracless annual output; anchor, not hourly cap. |
| `PEFA_C1_OPERATIONAL_FLEX_ANNUAL_MT` | Mt/y | 4.0-5.0 | 5.0 for standard-volume case | sensitivity / validation band | MER Heracless Table 5.1 | Annualised flexibility band; not DA-hourly ramping. |
| `PEFA_C1_IMPORTED_PELLETS_VARIANT_MT` | Mt/y | up to 2.5 instead of 0.2 | deferred sensitivity | validation / sensitivity anchor | MER Heracless §5.4 / Table 5.1 context | Used to test pellet-import relief; not base case. |
| `PEFA_IRON_ORE_INPUT_T_PER_T_PELLETS` | t/t pellets | 0.935-0.965 | 0.950 | base candidate | JRC BREF Table 4.1, p.215 | Main material conversion. Other additives deferred. |
| `PEFA_BENTONITE_KG_PER_T` | kg/t pellets | 4.1-6.8 | 5.45 | deferred detail | JRC BREF Table 4.1, p.215 | Binder; leave out first simple implementation unless needed for mass closure. |
| `PEFA_FLUX_ADDITIVES_KG_PER_T` | kg/t pellets | olivine 0-27.6; limestone 0-5; dolomite 0-13.5; quartzite 0-20 | deferred | deferred detail | JRC BREF Table 4.1, p.215 | Not needed in the first compact PeFa link. |
| `PEFA_ELECTRICITY_MWH_PER_T` | MWh/t pellets | 0.0150-0.0275 | 0.0213 | base candidate | JRC BREF Table 4.1: electricity 54-99 MJ/t | Captures PeFa electricity load per tonne pellets. |
| `PEFA_COG_BOFG_ENERGY_GJ_PER_T` | GJ/t pellets | 0.306 | 0.306 | base candidate | JRC BREF Table 4.1: COG/BOF gas 306 MJ/t, footnote for integrated NL plant | Combined COG/BOFG energy evidence. Controller eligibility separates BOFG to Malerij and COG to Branderij. |
| `PEFA_NG_ENERGY_GJ_PER_T` | GJ/t pellets | 0.014 | 0.014 | base candidate / backup | JRC BREF Table 4.1: natural gas 14 MJ/t, footnote for integrated NL plant | External fuel back-up. May become more important in C1 when COG/BOFG availability changes. |
| `PEFA_GAS_FUEL_TOTAL_GJ_PER_T` | GJ/t pellets | 0.320 | 0.320 | selected base candidate | Derived from JRC Table 4.1: 0.306 COG/BOF + 0.014 NG | Total gas heat demand for Option A. |
| `PEFA_COKE_BREEZE_OR_ANTHRACITE_GJ_PER_T` | GJ/t pellets | 0.342 | 0.342 | base candidate / CO2 driver | JRC BREF Table 4.1: coke breeze 342 MJ/t, footnote for integrated NL plant | Solid fuel in pellets / induration heat. Not a WAG controller. |
| `PEFA_TOTAL_EXTERNAL_FUEL_GJ_PER_T` | GJ/t pellets | 0.662 | 0.662 | derived check | `PEFA_GAS_FUEL_TOTAL_GJ_PER_T + PEFA_COKE_BREEZE_OR_ANTHRACITE_GJ_PER_T` | Useful sanity check against JRC heat-recovery discussion; not an independently sourced value. |
| `PEFA_GROSS_ENERGY_GJ_PER_T` | GJ/t pellets | approx. 1.4 | 1.4 | validation check | JRC BREF §4.3.8, p.229 | Gross energy for Dutch pelletisation plant; not a direct model input if fuel and electricity are separately modelled. |
| `PEFA_HEAT_RECUPERATION_GJ_PER_T` | GJ/t pellets | approx. 0.7 | 0.7 | validation / deferred detail | JRC BREF §4.3.8, p.229 | Internal heat recovery from induration/cooling. Do not model as dispatchable heat source in first version. |
| `PEFA_HOT_AIR_RECIRC_DUCT_GJ_PER_T` | GJ/t pellets | 0.0675 | 0.0675 | validation / deferred detail | JRC BREF §4.3.8, p.229 | Specific hot-air recirculation duct recovery; already part of plant design, not a free flexibility source. |
| `PEFA_WASTE_GAS_FLOW_NM3_PER_T` | Nm3/t pellets | 1940-2400 | 2170 | reporting / emissions | JRC BREF Table 4.1, p.215 | Off-gas reporting only; not useful WAG. |
| `PEFA_DIRECT_CO2_T_PER_T` | tCO2/t pellets | 0.017-0.193 | 0.105 if aggregate mode required | validation / sensitivity | JRC BREF Table 4.1: CO2 17-193 kg/t | Use as aggregate CO2 check. Do not add on top of explicit fuel-combustion CO2. |
| `PEFA_OPERATION_CLASS` | - | continuous upstream process | continuous, not DA-responsive | modelling policy | MER + Athanasiadis precedent | Production may follow annual/route needs; avoid hourly price-response behaviour. |

## Controller eligibility parameters

| Parameter ID | Allowed carriers | Status | Interpretation |
|---|---|---|---|
| `PEFA_MALERIJ_ALLOWED_FUELS` | `BOFG`, `NG` | base structure | Drying/grinding heat. JRC supports BOF gas or natural gas for the Dutch drying/grinding context. |
| `PEFA_BRANDERIJ_ALLOWED_FUELS` | `COG`, `NG` | base structure | Induration/firing heat. JRC supports COG use for the Dutch induration context; NG is a fallback/back-up carrier. |
| `PEFA_BFG_ALLOWED` | `false` in base | blocked / later sensitivity | Do not allow BFG into PeFa by default; this avoids an over-flexible generic WAG sink. |
| `PEFA_DIRECT_WAG_MARKET_VALUE` | `false` | forbidden | WAG value only through useful-energy substitution, never direct market valuation. |
| `PEFA_STAGE_GAS_SPLIT_REQUIRED` | `false` for Option A | selected first implementation | No fixed Malerij/Branderij gas split in first implementation. |
| `PEFA_STAGE_GAS_SPLIT_OPTION_B` | e.g. 0.35 / 0.65 | optional later guardrail | Not source-backed; only if Option A causes false gas-allocation behaviour. |

## Derived values and annual sanity checks

These are not primary input values; they are checks for model output and annual energy allocation.

| Derived check | Formula | C0 estimate | C1 estimate | Caveat |
|---|---|---:|---:|---|
| `PEFA_C0_ELECTRICITY_TWH_Y` | 4.6 Mt * 0.0150-0.0275 MWh/t | 0.069-0.127 TWh/y | - | Candidate check only. |
| `PEFA_C1_ELECTRICITY_TWH_Y` | 5.0 Mt * 0.0150-0.0275 MWh/t | - | 0.075-0.138 TWh/y | Candidate check only. |
| `PEFA_C0_GAS_FUEL_PJ_Y` | 4.6 Mt * 0.320 GJ/t | 1.47 PJ/y | - | Combined COG/BOFG/NG gas heat. |
| `PEFA_C1_GAS_FUEL_PJ_Y` | 5.0 Mt * 0.320 GJ/t | - | 1.60 PJ/y | Combined COG/BOFG/NG gas heat. |
| `PEFA_C0_COKE_BREEZE_PJ_Y` | 4.6 Mt * 0.342 GJ/t | 1.57 PJ/y | - | Solid fuel / CO2 driver. |
| `PEFA_C1_COKE_BREEZE_PJ_Y` | 5.0 Mt * 0.342 GJ/t | - | 1.71 PJ/y | Solid fuel / CO2 driver. |
| `PEFA_C0_TOTAL_EXTERNAL_FUEL_PJ_Y` | 4.6 Mt * 0.662 GJ/t | 3.05 PJ/y | - | Gas + coke breeze only. |
| `PEFA_C1_TOTAL_EXTERNAL_FUEL_PJ_Y` | 5.0 Mt * 0.662 GJ/t | - | 3.31 PJ/y | Gas + coke breeze only. |
| `PEFA_C0_GROSS_ENERGY_PJ_Y` | 4.6 Mt * 1.4 GJ/t | 6.44 PJ/y | - | Includes recuperation; do not add to fuel terms. |
| `PEFA_C1_GROSS_ENERGY_PJ_Y` | 5.0 Mt * 1.4 GJ/t | - | 7.00 PJ/y | Includes recuperation; do not add to fuel terms. |
| `PEFA_C0_CO2_KT_Y_AGGREGATE` | 4.6 Mt * 0.017-0.193 t/t | 78-888 kt/y | - | Aggregate check only. |
| `PEFA_C1_CO2_KT_Y_AGGREGATE` | 5.0 Mt * 0.017-0.193 t/t | - | 85-965 kt/y | Aggregate check only. |

## Validation anchors

### Long-term / full-model anchors

| Anchor | Value | Use | Source |
|---|---:|---|---|
| C0 PeFa pellet output | 4.6 Mt/y | Full-site material validation | MER Heracless Table 5.1 / §13.2 |
| C1 PeFa pellet output | 5.0 Mt/y | C1 material validation | MER Heracless Table 5.1 / §13.2 |
| C1 PeFa operational band | 4.0-5.0 Mt/y | Sensitivity and operational variation check | MER Heracless Table 5.1 |
| Larger pellet-import variant | up to 2.5 Mt/y instead of 0.2 Mt/y | Scenario where own PeFa is relieved | MER Heracless §5.4 |
| PeFa output to BF/DRI | model-derived | BF/DRP burden validation | Model output vs route material balance |

### Small PeFa implementation checks

| Check | Target / use |
|---|---|
| Pellet output | Main activity check. |
| Iron ore input | Material conversion check. |
| Electricity demand | Full-site electricity accounting check. |
| Gas fuel demand | COG/BOFG/NG allocation check. |
| Malerij BOFG/NG use | Controller eligibility check. |
| Branderij COG/NG use | Controller eligibility check. |
| Coke breeze / anthracite input | Solid-fuel and CO2-driver check. |
| Direct CO2 or fuel-derived CO2 | Emissions check, depending on accounting mode. |
| Waste gas flow | Emissions reporting only, not WAG balance. |

## CO2 handling

Two modes are possible. Do not mix them without explicit reconciliation.

### Aggregate mode

```text
PEFA_CO2[t] = P_PEFA[t] * PEFA_DIRECT_CO2_T_PER_T
```

Use `PEFA_DIRECT_CO2_T_PER_T = 0.105` only as a midpoint aggregate approximation if a simple CO2 output is required. Keep the full BREF range `0.017-0.193 tCO2/t pellets` for sensitivity.

### WAG/fuel-explicit mode

```text
CO2_PEFA[t] =
    CO2_from_COG_to_Branderij[t]
  + CO2_from_BOFG_to_Malerij[t]
  + CO2_from_NG_to_PeFa[t]
  + CO2_from_coke_breeze_or_anthracite[t]
```

In this mode, the BREF CO2 range is a validation target only and must not be added as a separate process-emission output.

## Simplified pellet burden / BF-DRP balance layer

This candidate section supports the first simplified fired-pellet burden balance after the PeFa accounting layer. It uses one generic material carrier:

```text
fired_pellets_proxy
```

The proxy deliberately does not distinguish BF-grade and DR-grade pellets. It also does not model Fe content, basicity, gangue, moisture, pellet chemistry, strict stockpile or silo capacity, pellet quality constraints, or hidden Tata burden recipes. The layer is a public-data development reconciliation, not Tata operating truth and not thesis-approved.

| Parameter | Selected / check value | Formula or basis | Status | Caveat |
|---|---:|---|---|---|
| `PELLET_GRADE_MODE` | `single_fired_pellets_proxy` | Modelling policy | development assumption | No BF-grade / DR-grade distinction in first implementation. |
| `BF_PELLET_INPUT_T_PER_T_HM_C0_DERIVED` | `0.968` | `(4.6 + 1.5) / (2.5 + 3.8)` | Tata/MER-derived annual reconciliation candidate | Not an independent BF technology coefficient; used to reconcile C0 annual pellet supply with BF hot-metal output. |
| `BF_PELLET_INPUT_T_PER_T_HM_C1_RESIDUAL` | approx. `0.506` | `(5.0 + 0.2 - 2.8 * (1 / 0.74)) / 2.8` | C1 residual mass-balance reconciliation candidate | Not an independent BF6 burden value; depends on DRP pellet coefficient, PeFa output and import anchor. |
| `BF_PELLET_INPUT_T_PER_T_HM_GENERIC_BREF` | `0.358` check; range `0-0.972` | Generic BREF-style burden benchmark | external benchmark / sensitivity only | Do not use the weighted average as Tata base if it conflicts with MER annual anchors. |
| `DRP_PELLET_INPUT_T_PER_T_DRI` | `1.351351` | `1 / 0.74` | base candidate from existing DRP-yield/project precedent | Modelling precedent, not confidential Tata truth. |
| `DRP_PELLET_INPUT_T_PER_T_DRI_SENS` | `1.39` | sanity-check sensitivity | candidate / deferred unless existing evidence is active | Do not activate in the base pellet balance without a sensitivity stage. |
| `PEFA_PELLETS_ELIGIBLE_FOR_BF` | `true` | Site topology assumption | base assumption / source-supported topology | Generic proxy ignores grade details. |
| `PEFA_PELLETS_ELIGIBLE_FOR_DRP` | `true` | Site topology assumption | base assumption with quality caveat | Requires explicit caveat because DR-grade quality is not modelled. |
| `IMPORTED_PELLETS_ALLOWED` | `true` | Public MER import context | base policy | Exogenous development supply, not free optimisation slack. |
| `IMPORTED_PELLETS_C0_ANCHOR_MT_Y` | `1.5` | MER annual context | validation anchor / development supply candidate after scaling | Anchor must not become a hidden hourly dispatch constraint. |
| `IMPORTED_PELLETS_C1_BASE_MT_Y` | `0.2` | MER base context | validation anchor / base scenario after scaling | Anchor must not become a free slack variable. |
| `IMPORTED_PELLETS_C1_VARIANT_CAP_MT_Y` | `2.5` | MER variant context | sensitivity / variant cap, not base | Variant for later import-relief sensitivity only. |
| `IMPORTED_PELLETS_SCALING_MODE` | `scale_with_active_production_target` | Existing C5 active-target convention | modelling policy | Use the same C5 scaling convention as PeFa and KGF anchors. |
| `PELLET_BALANCE_MODE` | `inventory_balance_practically_unlimited_capacity` | Bulk-solid accounting policy | modelling policy | Non-binding capacity does not mean free supply. |
| `BULK_SOLID_STORAGE_CAPACITY_MODE` | `practically_non_binding_bulk_solid_storage` | Applies to coke, sinter and fired pellets proxy | modelling policy | Capacity should not bind, but terminal and inventory diagnostics must prevent fake feasibility. |
| `PELLET_GAP_SURPLUS_MODE` | `diagnostic_inventory_drift_and_healthcheck` | Healthcheck policy | modelling policy | No hidden solver slack for thesis claims. |
| `PELLET_GAP_TOLERANCE_REL` | `1%` | Rounded public annual values | healthcheck threshold | Practical tolerance only. |
| `PELLET_GAP_TOLERANCE_MT_Y` | `0.05` | Rounded public annual values | healthcheck threshold | Practical tolerance only. |

The first executable layer should report raw and active-scaled anchors, resolved BF and DRP pellet coefficients, fixed imported-pellet supply, pellet inventory drift, and any diagnostic gap or surplus. It must not use validation anchors as hidden hourly constraints.

## Deferred details

The first implementation should not model:

- exact pellet chemistry and Fe content;
- bentonite, olivine, limestone, dolomite and quartzite as separate active optimisation flows;
- exact drying-zone and firing-zone heat balances;
- dynamic moisture and pellet quality;
- NOx, SOx, HF, HCl, PCDD/F, PAH and heavy-metal control;
- LoTOx/DeNOx chemistry;
- detailed waste-gas recirculation;
- dispatchable heat recovery;
- detailed Wobbe-index control.

## Source cards / full references

### S1 — MER Heracless / Tata-specific topology and anchors

**Title:** *MER Heracless - Groen Staal, Deel B: Technische beschrijving*
**Organisation / client:** Haskoning Nederland B.V. for Tata Steel IJmuiden B.V.
**Year:** 2025, definitive version 15 September 2025
**URL:** https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf
**Relevant locators:** §3.2.2 Pelletfabriek; §5.4 Production volumes; Table 5.1; §13.2 Pelletfabriek; §4.2 DeNOx op Pelletfabriek.
**Values used:** PeFa output 4.6 Mt/y reference; PeFa output 5.0 Mt/y Heracless; Heracless operational band 4.0-5.0 Mt/y; larger imported-pellets variant up to 2.5 Mt/y instead of 0.2 Mt/y.
**Caveat:** Strong public Tata topology and annual-anchor source. Does not provide full per-ton conversion factors for the simplified MILP.

### S2 — JRC BREF / candidate conversion factors

**Title:** *Best Available Techniques (BAT) Reference Document for Iron and Steel Production*
**Authors:** Rainer Remus, Miguel A. Aguado-Monsonet, Serge Roudier, Luis Delgado Sancho
**Organisation:** European Commission Joint Research Centre / European IPPC Bureau
**Year:** 2013
**DOI:** 10.2791/97469
**URL:** https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/IS_Adopted_03_2012.pdf
**Relevant locators:** Chapter 4 Pelletisation; Figure 4.6 mass stream overview; Table 4.1 Input/output data from three pellet plant sites in the EU-25; §4.3.8 Recovery of sensible heat from the induration strand.
**Values used:** iron ore 935-965 kg/t pellets; COG/BOF gas 306 MJ/t; natural gas 14 MJ/t; coke breeze 342 MJ/t; electricity 54-99 MJ/t; waste gas 1940-2400 Nm3/t; CO2 17-193 kg/t; gross energy approx. 1.4 GJ/t; recuperated heat approx. 0.7 GJ/t; hot-air recirculation duct approx. 67.5 MJ/t.
**Caveat:** Values are high-authority generic/European candidate evidence, not exact Tata operating data. Some energy rows are explicitly for the integrated Dutch plant, but still not an executable Tata input without review.

### S3 — Athanasiadis / modelling precedent

**Title:** *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site*
**Author:** Ioannis Athanasiadis
**Institution:** TU Delft MSc Sustainable Energy Technologies
**Year:** 2025
**Relevant locators:** §3.3.1 Main Plants; Figure 22 Pelletizing Plant PyPSA modelling approach; gas network/controller sections.
**Use:** Supports splitting Pelletizing Plant into Malerij and Branderij and using WAG controllers.
**Caveat:** Public thesis is a modelling precedent, not a source of exact public Tata numerical conversion factors.

## Recommended first implementation values

```text
PEFA_OUTPUT_BASIS = t fired pellets

PEFA_IRON_ORE_INPUT_T_PER_T_PELLETS = 0.950
PEFA_ELECTRICITY_MWH_PER_T           = 0.0213
PEFA_GAS_FUEL_TOTAL_GJ_PER_T         = 0.320
PEFA_COG_BOFG_ENERGY_GJ_PER_T        = 0.306
PEFA_NG_ENERGY_GJ_PER_T              = 0.014
PEFA_COKE_BREEZE_OR_ANTHRACITE_GJ_PER_T = 0.342

PEFA_MALERIJ_ALLOWED_FUELS   = [BOFG, NG]
PEFA_BRANDERIJ_ALLOWED_FUELS = [COG, NG]
PEFA_BFG_ALLOWED             = false

PEFA_DIRECT_CO2_T_PER_T = validation_only_range_0.017_to_0.193
```

Base modelling choice:

```text
Use Option A for first implementation.
Do not impose a fixed Malerij/Branderij gas split unless diagnostics show false gas allocation.
```

## C0 temporal development status (2026-08-05)

The C0 temporal model represents PeFa production (4.3125 Mt/y comparison basis)
and source-backed pellet imports (1.40625 Mt/y) as separate origins feeding a
closed pellet inventory. PeFa uses 465.75--513.1875 t/h, four-hour setpoints and
at most 6.9 t/h change per setpoint. These are development constraints, not
source-certified operating limits. PeFa stays at its lower bound in the accepted
high-volatility week; no artificial flexibility or bound widening was added.

## Pellet-origin ledger status (2026-08-05)

The deterministic C0/C1 temporal builders now conserve pellet origins
explicitly. Internal PeFa pellets, external BF-grade pellets and external
DR-grade pellets are separate accounting flows. In C0, the normalized
1.40625-Mt/y external origin can feed only the BF route. In C1, the 0.2-Mt/y
external origin can feed only the DRP; PeFa output supplies the remaining BF
and DRP pellet demand through a carried internal inventory. Only the two
external origins receive a pellet purchase price.

This closes origin conservation and prevents all DRP pellet input from being
misclassified as imported. It does not prove that every internal PeFa pellet
meets DR-grade specifications: internal PeFa quality remains a generic fired-
pellet proxy pending source evidence on product grades, blending and storage.
