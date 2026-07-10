# IJ01 and VN25 WAG Electricity Generator Parameters

## Purpose

This source-card memo defines a compact, source-backed parameter and modelling surface for the IJmond/Velsen WAG electricity generators that are relevant to the Tata Steel IJmuiden-inspired steel model:

- `VN25` / Velsen-Noord 25;
- `IJ01` / IJmond 01;
- `VN24` only as a documented backup unit, not an active base-case unit.

The memo is intended for the same source-to-input workflow as the other plant notes:

1. source evidence and source-card interpretation;
2. candidate values, validation anchors, assumptions and sensitivities;
3. later reviewed migration into executable development inputs;
4. no direct promotion to thesis-approved numerical truth.

## Scope and base-case decision

The first implementation should include IJ01 and VN25 as a **WAG/NG electricity-generation interface**, not as a detailed Vattenfall/Tata power-plant digital twin.

Base-case role:

```text
VN25 = primary C1 residual-gas electricity generator
IJ01 = CHP / backup generator in the C1 preferred configuration
VN24 = cold/backup reserve only, excluded from active base-case dispatch
```

Base-case market treatment:

```text
GENERATOR_ELECTRICITY_VALUE_MODE = offset_site_grid_import
GENERATOR_EXPORT_REVENUE_ENABLED_BASE = false
GENERATOR_PRICE_RESPONSIVE_DISPATCH_BASE = false
GENERATOR_MFRR_ENABLED_BASE = false
```

This means generated electricity reduces modelled site grid import or full-site electricity exposure. It is **not** treated as export revenue in the first base case. This avoids allowing WAG-generator dispatch to dominate the thesis results before the full physical and economic C0/C1 scope is stable.

## Why not fully flexible in the base case?

Athanasiadis models the WAG electricity generators as part of a cost-optimising gas/electricity system. This is useful as a precedent, but the public version also makes clear that the real gas network is complex, involving gas mixing, Wobbe-index control, real-time properties, contracts and operating constraints. The generator operation should therefore not be interpreted as a fully free, hourly price-responsive market plant in the first Tata-inspired MILP.

The first steel model should use the generators primarily to:

- absorb available WAGs where source-supported;
- reduce net grid import / reconcile full-site electricity;
- expose shortages of WAG absorption capacity through flaring diagnostics;
- make the Heracless C1 WAG-system change visible.

The first model should not use the generators to:

- create direct electricity-export revenue;
- offer mFRR;
- optimise power-plant commitment against DA prices;
- claim Tata/Vattenfall contract behaviour;
- use hidden transfer prices or confidential dispatch rules.

## Source hierarchy

| Rank | Source | Use | Confidence and caveat |
|---:|---|---|---|
| 1 | Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025), *Detailstudie Energie en CO2-balans MER Heracless* | Main source for Heracless C1 generator use, VN25/IJ01 operating roles, hours, fuel use by gas type, and the IJ01-as-base variant. | High for public C1 planning anchors. Values are annual scenario assumptions and validation anchors, not hourly dispatch constraints. |
| 2 | Tata Steel Nederland / Vattenfall press releases (2025) | Ownership transfer, role of units, residual-gas use, IJ01 as CHP producing electricity and steam. | High for ownership/functionality. Does not give detailed unit parameters. |
| 3 | Vattenfall N.V. Annual Report 2025 | Confirms transfer of IJmond 1, Velsen 24 and Velsen 25 and residual-gas electricity supply to Tata Steel. | High for corporate transaction context, limited technical detail. |
| 4 | Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025), QRA current and QRA Heracless | Fuel-network context and consumer lists for BFG/COG/product gases. | Medium/high for fuel eligibility; not an energy-dispatch manual. |
| 5 | Tata Steel Limited exchange announcement (2025) | Total electric capacity of the transferred Velsen Power Plants, 770 MW. | High for total capacity, but not per-unit capacity. |
| 6 | Athanasiadis (2025) | PyPSA modelling precedent for WAG generator links and VN25 development capacity. | Modelling precedent only; not public Tata-approved numerical truth. |

## Recommended PyPSA abstraction

### Buses

```text
bfg_bus
bofg_bus
cog_bus
natural_gas_bus
vn25_fuel_energy_bus
ij01_fuel_energy_bus
electricity_internal_bus
steam_or_heat_ij01_bus     # optional / deferred
co2_bus
flare_or_spill_bus
```

### Links

For VN25:

```text
BFG_to_VN25_fuel
BOFG_to_VN25_fuel
COG_to_VN25_fuel
NG_to_VN25_fuel

VN25_generator_link:
    vn25_fuel_energy_bus -> electricity_internal_bus + CO2
```

For IJ01:

```text
BFG_to_IJ01_fuel
BOFG_to_IJ01_fuel
COG_to_IJ01_fuel

IJ01_CHP_link:
    ij01_fuel_energy_bus -> electricity_internal_bus + steam_or_heat_ij01_bus + CO2
```

For the first implementation, it is acceptable to simplify IJ01 as electricity-only plus a deferred steam-output placeholder, because the public sources confirm CHP functionality but do not give a robust electricity/steam split for Heracless.

### Fuel mixing and WAG control

The WAG generator fuel should be modelled in **energy units** first. Avoid an exact Wobbe-index formulation in the first LP/MILP. Use gas-specific eligibility and energy balances:

```text
VN25_fuel_energy[t] =
    BFG_to_VN25[t] + BOFG_to_VN25[t] + COG_to_VN25[t] + NG_to_VN25[t]

IJ01_fuel_energy[t] =
    BFG_to_IJ01[t] + BOFG_to_IJ01[t] + COG_to_IJ01[t]
```

A later gas-quality layer may add Wobbe/LHV constraints, but the base model should not overfit public data that do not describe the real burner/control system.

## Implementation modes

### Mode A: fixed/interface mode (recommended first)

```text
GENERATOR_DISPATCH_MODE = fixed_or_validation_scaled_interface
```

Characteristics:

- VN25 and IJ01 are represented as WAG/NG sinks with source-backed annual validation anchors.
- Electricity generation is an internal offset to grid import.
- No hourly DA price response.
- No export revenue.
- No mFRR.
- Fuel-use gaps and flaring are reported.

This is safest for the first unified C0/C1 physical-economic model because it captures the functional presence of the generators without letting them dominate the optimisation.

### Mode B: constrained flexible WAG-absorption mode (later sensitivity)

```text
GENERATOR_DISPATCH_MODE = constrained_wag_absorption
```

Characteristics:

- The optimiser may allocate WAGs between VN25, IJ01, boilers and flaring subject to fuel eligibility, annual fuel-use envelopes and capacity limits.
- Generated electricity still offsets site import only.
- No DA export revenue.
- No mFRR.

This is useful for testing whether the WAG system can absorb available gases after BF7/KGF2 closure. It is not a forecast-quality experiment unless all other policies are fixed.

### Mode C: price-responsive generator sensitivity (not base)

```text
GENERATOR_DISPATCH_MODE = price_responsive_sensitivity
GENERATOR_EXPORT_REVENUE_ENABLED = true or explicitly valued
```

Characteristics:

- Generator dispatch may respond to DA prices.
- Export or power-price revenue may be modelled.
- This changes the economic policy and must be reported as an energy-system policy sensitivity.

This mode should not be used in the base steel thesis comparison, because it can turn the analysis into WAG-electricity arbitrage rather than process-flexibility analysis.

## Core parameter table

| Parameter ID | Recommended value | Unit | Status | Source ID | Use and caveat |
|---|---:|---|---|---|---|
| `VN25_ENABLED_BASE` | `true` | bool | base candidate | S1, S2 | VN25 is the primary generator in the Heracless preferred configuration. |
| `IJ01_ENABLED_BASE` | `true` | bool | base candidate | S1, S2 | IJ01 is present as CHP and backup/reserve generator. |
| `VN24_ENABLED_BASE` | `false` | bool | base policy | S1 | VN24 is documented as cold/backup reserve and excluded from the first active base case. |
| `VN25_ROLE_C1` | `primary_residual_gas_generator` | text | base candidate | S1 | VN25 is the main C1 residual-gas generator in the preferred option. |
| `IJ01_ROLE_C1` | `chp_backup_or_reserve` | text | base candidate | S1, S2 | IJ01 is backup in the preferred option and CHP by function. |
| `GENERATOR_ELECTRICITY_VALUE_MODE` | `offset_site_grid_import` | policy | base policy | S1, project policy | Electricity output reduces site electricity exposure; no direct export revenue. |
| `GENERATOR_EXPORT_REVENUE_ENABLED_BASE` | `false` | bool | base policy | project policy | Direct power-market revenue is deferred. |
| `GENERATOR_PRICE_RESPONSIVE_DISPATCH_BASE` | `false` | bool | base policy | project policy, S6 | Avoids turning WAG allocation into DA-price arbitrage. |
| `GENERATOR_MFRR_ENABLED_BASE` | `false` | bool | base policy | project policy | No reserve claim without plant deliverability evidence. |
| `VN25_OPERATION_SHARE_C1_TEXT` | `0.85` | fraction | validation / planning anchor | S1 | MER variant table says VN25 at 85% capacity and IJM01 backup at 15%. |
| `IJ01_OPERATION_SHARE_C1_TEXT` | `0.15` | fraction | validation / planning anchor | S1 | Same source; planning share, not hourly dispatch rule. |
| `VN25_OPERATION_HOURS_C1_TEXT` | `~7500` | h/y | validation anchor | S1 | MER text states approximately 7,500 h/y at partial load. |
| `VN25_OPERATION_LOAD_C1_TEXT` | `~0.50` | fraction load | validation anchor | S1 | MER text states VN25 operates at about 50% part load. |
| `IJ01_OPERATION_HOURS_C1_TEXT` | `~1300` | h/y | validation anchor / conflict | S1 | MER text states about 1,300 h/y; Table 5.5 gives 899 h/y. Report discrepancy. |
| `VN25_OPERATION_HOURS_C1_TABLE` | `7519` | h/y | validation anchor | S1 Table 5.5 | Table-based preferred anchor for fuel-use scenario. |
| `IJ01_OPERATION_HOURS_C1_TABLE` | `899` | h/y | validation anchor | S1 Table 5.5 | Use as table-based anchor; keep text conflict visible. |
| `VATTENFALL_TOTAL_CAPACITY_MW` | `770` | MW | source-card anchor | S5 | Official total electric capacity of transferred Velsen Power Plants. Not per-unit capacity. |
| `VN25_ELECTRIC_CAPACITY_MW_DEV` | `350` | MW | development candidate | S6 | Athanasiadis model precedent only; not an official public unit capacity. |
| `VN25_WAG_CAPACITY_M3_H_DEV` | `600000` | m3/h | development candidate | S6 | Athanasiadis model precedent only; use only with caveat if a gas-throughput cap is needed. |
| `IJ01_ELECTRIC_CAPACITY_MW` | `deferred` | MW | deferred | S1, S2 | IJ01 capacity is not robustly source-backed in the sources used here. |
| `VN25_ELECTRIC_EFFICIENCY_DEV` | `0.34-0.35` | MWh_e/MWh_fuel | derived / development-only | S1 + S6 | Approximate from VN25 350 MW, 50% load, 7519 h/y and 13.7 PJ/y fuel. Do not use as thesis-approved efficiency. |
| `IJ01_ELECTRIC_EFFICIENCY_DEV` | `deferred` | MWh_e/MWh_fuel | deferred | S1 | IJ01 is CHP; electricity/steam split not source-backed enough. |
| `IJ01_STEAM_OUTPUT_ENABLED` | `true` | bool | structure candidate | S2 | Press releases state IJ01 produces electricity and steam. Quantitative output deferred. |
| `VN25_STEAM_OUTPUT_ENABLED` | `false` | bool | base candidate | S2 | VN25 treated as electricity-only in first abstraction. |

## C1 preferred-configuration fuel anchors: VN25 as base unit

All values below are **annual validation anchors**, not hourly constraints.

| Parameter ID | Value | Unit | Status | Source ID | Use and caveat |
|---|---:|---|---|---|---|
| `VN25_BFG_C1_PJ_Y` | `8.4` | PJ/y | validation anchor | S1 Table 5.5 | Preferred configuration, VN25 as base unit. |
| `VN25_BOFG_C1_PJ_Y` | `1.2` | PJ/y | validation anchor | S1 Table 5.5 | BOFG/oxygas to VN25. |
| `VN25_COG_C1_PJ_Y` | `0.1` | PJ/y | validation anchor | S1 Table 5.5 | Small COG use. |
| `VN25_NG_C1_PJ_Y` | `4.1` | PJ/y | validation anchor / base external gas | S1 Table 5.5 | Table value; MER text mentions 3.8 PJ/y NG. Keep discrepancy visible. |
| `VN25_TOTAL_FUEL_C1_PJ_Y` | `13.7` | PJ/y | validation anchor | S1 Table 5.5 | Total VN25 fuel in preferred configuration. |
| `IJ01_BFG_C1_PJ_Y` | `0.7` | PJ/y | validation anchor | S1 Table 5.5 | IJ01 limited/reserve operation. |
| `IJ01_BOFG_C1_PJ_Y` | `0.1` | PJ/y | validation anchor | S1 Table 5.5 | IJ01 limited/reserve operation. |
| `IJ01_COG_C1_PJ_Y` | `0.0` | PJ/y | validation anchor | S1 Table 5.5 | Rounded zero. COG eligibility remains caveated. |
| `IJ01_NG_C1_PJ_Y` | `0.0` | PJ/y | validation anchor | S1 Table 5.5 | Base: no NG to IJ01. |
| `IJ01_TOTAL_FUEL_C1_PJ_Y` | `0.8` | PJ/y | validation anchor | S1 Table 5.5 | Total IJ01 fuel in preferred configuration. |
| `GENERATOR_FLARE_C1_PJ_Y` | `0.1` | PJ/y | validation anchor | S1 Table 5.5 | Explicit flaring anchor. |
| `GENERATOR_TOTAL_FUEL_C1_PJ_Y` | `14.6` | PJ/y | validation anchor | S1 Table 5.5 | VN25 + IJ01 + flare. |

## C1 sensitivity fuel anchors: IJ01 as base unit

These values are for the MER variant where IJ01 is the main residual-gas user. They should be used only as a sensitivity / variant validation set.

| Parameter ID | Value | Unit | Status | Source ID | Use and caveat |
|---|---:|---|---|---|---|
| `VN25_BFG_IJ01_BASE_VARIANT_PJ_Y` | `0.9` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant with IJ01 as base unit. |
| `VN25_BOFG_IJ01_BASE_VARIANT_PJ_Y` | `0.1` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `VN25_COG_IJ01_BASE_VARIANT_PJ_Y` | `0.0` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `VN25_NG_IJ01_BASE_VARIANT_PJ_Y` | `0.7` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `VN25_TOTAL_FUEL_IJ01_BASE_VARIANT_PJ_Y` | `1.7` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `IJ01_BFG_IJ01_BASE_VARIANT_PJ_Y` | `7.5` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `IJ01_BOFG_IJ01_BASE_VARIANT_PJ_Y` | `0.9` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `IJ01_COG_IJ01_BASE_VARIANT_PJ_Y` | `0.0` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `IJ01_NG_IJ01_BASE_VARIANT_PJ_Y` | `0.0` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `IJ01_TOTAL_FUEL_IJ01_BASE_VARIANT_PJ_Y` | `8.3` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `VN25_OPERATION_HOURS_IJ01_BASE_VARIANT` | `961` | h/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `IJ01_OPERATION_HOURS_IJ01_BASE_VARIANT` | `7418` | h/y | sensitivity anchor | S1 Table 5.5 | Variant. |
| `GENERATOR_TOTAL_FUEL_IJ01_BASE_VARIANT_PJ_Y` | `10.0` | PJ/y | sensitivity anchor | S1 Table 5.5 | Variant total. |
| `GENERATOR_FUEL_SAVING_VARIANT_PJ_Y` | `3.5` | PJ/y | sensitivity diagnostic | S1 Table 5.5 | Difference relative to preferred configuration. |

## Fuel eligibility

| Parameter ID | Value | Unit | Status | Source ID | Use and caveat |
|---|---|---|---|---|---|
| `VN25_ALLOWED_FUELS_BASE` | `BFG;BOFG;COG;NG` | carriers | base candidate | S1 Table 5.5 | All four have nonzero annual use in preferred configuration. |
| `IJ01_ALLOWED_FUELS_BASE` | `BFG;BOFG;COG` | carriers | base/caveated | S1, S2 | BFG and BOFG are table-supported. COG is residual-gas eligibility but rounded zero in Table 5.5. |
| `IJ01_NG_ALLOWED_BASE` | `false` | bool | base candidate | S1 Table 5.5 | NG use is zero in both Table 5.5 configurations. |
| `VN25_NG_ALLOWED_BASE` | `true` | bool | base candidate | S1 Table 5.5 | NG is required to run VN25 as the base unit in C1. |
| `BOFG_TO_GENERATORS_AS_SEPARATE_CARRIER` | `true` | bool | base candidate | S1 Table 5.5, project WAG policy | Keep BOFG separate, not hidden inside generic WAG. |
| `GENERIC_WAG_TO_GENERATORS` | `false` | bool | base policy | project WAG policy | Use BFG/BOFG/COG carriers explicitly. |

## Capacity, efficiency and conversion treatment

The public sources give strong annual fuel-use anchors but weak per-unit electrical efficiencies. Therefore:

```text
VN25_ELECTRIC_CAPACITY_MW_DEV = 350      # development only, Athanasiadis precedent
VN25_ELECTRIC_EFFICIENCY_DEV ≈ 0.34-0.35 # derived from development capacity + MER fuel/hours
IJ01_ELECTRIC_EFFICIENCY_DEV = deferred  # CHP split not source-backed
```

Recommended first implementation:

1. Use annual fuel anchors to validate the gas allocation.
2. Use a development electricity conversion only for smoke tests.
3. Keep generator electricity as a grid-import offset.
4. Do not thesis-report generator profit or export revenue until a better source-backed conversion and boundary convention exists.

## Annual validation anchors

| Anchor ID | Value | Unit | Source ID | Use |
|---|---:|---|---|---|
| `CURRENT_PRODUCT_GAS_REUSE_ANNUAL` | `54` | PJ/y | MER Deel B / source-card context | Current WAG energy reuse for electricity/heat at Tata or Vattenfall. |
| `CURRENT_TATA_AVG_ELECTRIC_POWER` | `360` | MW | MER Deel B / source-card context | Current electricity demand anchor. |
| `CURRENT_VATTENFALL_RESIDUAL_GAS_ELECTRICITY` | `2.0` | TWh/y | Tata annual/corporate context, secondary | C0 sanity check only. |
| `C1_VN25_TOTAL_FUEL` | `13.7` | PJ/y | S1 Table 5.5 | Preferred C1 WAG/NG generator validation. |
| `C1_IJ01_TOTAL_FUEL` | `0.8` | PJ/y | S1 Table 5.5 | Preferred C1 backup-generator validation. |
| `C1_GENERATOR_FLARING` | `0.1` | PJ/y | S1 Table 5.5 | WAG surplus/flaring diagnostic. |
| `C1_IJ01_BASE_VARIANT_TOTAL_FUEL` | `10.0` | PJ/y | S1 Table 5.5 | Sensitivity validation. |
| `TRANSFERRED_POWER_PLANTS_TOTAL_CAPACITY` | `770` | MW | S5 | Total capacity context, not per-unit input. |

## Small implementation checks

| Check | Purpose |
|---|---|
| `BFG_to_VN25`, `BOFG_to_VN25`, `COG_to_VN25`, `NG_to_VN25` | Check preferred C1 generator fuel allocation. |
| `BFG_to_IJ01`, `BOFG_to_IJ01`, `COG_to_IJ01` | Check backup/variant generator fuel allocation. |
| `generator_fuel_unserved_or_gap` | Reveal WAG-system closure problems. |
| `generator_flare_or_spill` | Track gas that cannot be absorbed by process sinks, boilers or generators. |
| `electricity_offset_from_generators` | Check full-site electricity accounting. |
| `gas_to_electricity_efficiency_warning` | Prevent thesis use of unreviewed development efficiency. |
| `generator_price_response_flag` | Ensure base runs do not silently include price-responsive generator dispatch. |

## Model red flags

- Do not let generator export revenue enter the base objective.
- Do not use IJ01/VN25 as mFRR assets without separate deliverability evidence.
- Do not combine BFG/COG/BOFG into one generic WAG without explicit carrier tracking.
- Do not silently use Athanasiadis' VN25 350 MW as official Tata public capacity.
- Do not use the 770 MW total capacity as a VN25 or IJ01 capacity.
- Do not allow generators to consume unlimited WAGs without annual validation, capacity or flaring diagnostics.
- Do not interpret Table 5.5 annual values as hourly dispatch schedules.
- Do not compare forecast/scenario quality while changing generator revenue policy.

## Source appendix

### S1 — Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025)

**Title:** *Detailstudie Energie en CO2-balans MER Heracless*
**Reference:** BI3580-IB-RP
**Date:** 15 September 2025
**URL:** https://pas.commissiemer.nl/files/nl/3730/01-Energie.pdf
**Used sections:** Section 5.7.2.2-5.7.2.4; Table 5.5; Section 6.3.1 where relevant.
**Used values and statements:**

- VN24 is mainly cold reserve in the current situation; VN25 and IJM01 operate most of the year.
- In Heracless, there is not enough product gas to run both VN25 and IJM01 most of the year.
- Preferred configuration: VN25 runs most of the year, about 7,500 h/y, at about 50% part load; IJM01 is mainly reserve.
- Text value: IJM01 about 1,300 h/y in that configuration.
- Text value: about 3.8 PJ/y natural gas needed for VN25.
- Table 5.5 preferred configuration: VN25 BFG 8.4 PJ/y, BOFG 1.2 PJ/y, COG 0.1 PJ/y, NG 4.1 PJ/y, total 13.7 PJ/y, 7,519 h/y.
- Table 5.5 preferred configuration: IJM01 BFG 0.7 PJ/y, BOFG 0.1 PJ/y, COG 0.0 PJ/y, NG 0.0 PJ/y, total 0.8 PJ/y, 899 h/y.
- Table 5.5 IJM01-as-base variant: VN25 total 1.7 PJ/y and 961 h/y; IJM01 total 8.3 PJ/y and 7,418 h/y.
- Table 5.5 states source as Tata Steel.

**Caveat:** Annual scenario/planning anchors, not hourly dispatch constraints.

### S2 — Tata Steel Nederland / Vattenfall press release (2025)

**Title:** *Tata Steel Nederland to acquire Vattenfall power plants in IJmond region*
**Organisation:** Tata Steel Nederland / Vattenfall
**Date:** 14 November 2025
**URL:** https://www.tatasteelnederland.com/nieuws/en/tata-steel-nederland-to-acquire-vattenfall-power-plants-in-ijmond-region
**Alternative URL:** https://group.vattenfall.com/press-and-media/pressreleases/2025/tata-steel-nederland-to-acquire-vattenfall-power-plants-in-ijmond-region/
**Used values and statements:**

- Tata Steel Nederland acquires the Vattenfall power plants in the IJmond region.
- Ownership transfers on 1 January 2026.
- Velsen-Noord 24 and 25 generate electricity predominantly from steel-production residual gases.
- IJmond 01 is a CHP plant on the Tata Steel site, fuelled by residual gases, producing electricity and steam.
- Electricity and steam are used in steel-plant operational processes.

**Caveat:** Strong for role/function and ownership, not for unit efficiencies or dispatch.

### S3 — Vattenfall N.V. (2026)

**Title:** *Vattenfall N.V. Annual Report 2025*
**Organisation:** Vattenfall N.V.
**Publication year:** 2026
**URL:** https://www.vattenfall.nl/media/4.-over-vattenfall-corporate/6.-downloads/vattenfall-nv-annual-report-2025_final_accessible-versie.pdf
**Used values and statements:**

- Vattenfall and Tata Steel finalised the transfer of IJmond 1, Velsen 24 and Velsen 25 in 2025.
- The plants are located on and near Tata Steel's IJmuiden site.
- They use residual gases from Tata Steel production processes to generate electricity supplied to Tata Steel.
- Ownership transferred to Tata Steel in January 2026.

**Caveat:** Corporate confirmation; limited technical detail.

### S4 — Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025), QRA current situation

**Title:** *Detailstudie Externe Veiligheid - QRA actuele bedrijfssituatie*
**Reference:** BI3580-IB-RP
**Date:** 15 September 2025
**URL:** https://pas.commissiemer.nl/files/nl/3730/11-a-Veiligheid-referentie.pdf
**Used values and statements:**

- Current gas-network context and consumer lists for BFG/COG.
- Used to support carrier eligibility, not dispatch levels.

**Caveat:** Safety/QRA source, not an economic dispatch source.

### S5 — Tata Steel Limited exchange announcement (2025)

**Title:** *Disclosure under Regulation 30 of SEBI Listing Regulations: acquisition of LAG Velsen B.V. / Velsen Power Plants*
**Organisation:** Tata Steel Limited
**Date:** 14 November 2025
**URL:** https://www.tatasteel.com/media/25040/tata-steel-announcement-ld.pdf
**Used values and statements:**

- Velsen Power Plants total electric capacity: 770 MW.
- The transferred entity/power plants are part of the transaction.

**Caveat:** Total capacity only. Do not use as VN25 or IJ01 unit capacity.

### S6 — Athanasiadis, I. (2025)

**Title:** *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site*
**Author:** Ioannis Athanasiadis
**Institution:** Delft University of Technology
**Date:** 17 February 2025
**Local file:** `Master_Thesis_Report_Athanasiadis (1).pdf`
**Used values and statements:**

- PyPSA modelling precedent for WAG electricity generators as Link-like components.
- WAG generator behaviour in the gas-network model.
- VN25 development precedent: 350 MW electricity generation and 600,000 m3/h WAG nominal capacity.
- Warning that real gas-network operation is more complex than hourly modelled behaviour.

**Caveat:** Public thesis precedent. Not an official Tata public parameter table and not automatically executable/thesis-approved.
