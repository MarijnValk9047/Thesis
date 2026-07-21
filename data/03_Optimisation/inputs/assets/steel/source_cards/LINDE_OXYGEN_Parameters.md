# LINDE Oxygen / Air Separation Parameters

## Purpose

Compact source-card memo for the Linde oxygen / air-separation layer in the public Tata Steel
IJmuiden-inspired MILP.

The goal is to represent oxygen as a shared utility carrier that couples BF, BOF/OSF, EAF and
NG-DRP operation to a central Linde/ASU electricity-consuming production link and a short-term
oxygen balancing buffer.

This memo is **not** an approved executable input table. It records source-backed candidate values,
validation anchors, modelling policy choices, caveats, and deferred details.

## Scope and first implementation decision

### Included in first implementation

- Gaseous oxygen production to a site `oxygen_bus`.
- Electricity demand of oxygen production using a generic ASU benchmark.
- A small oxygen buffer/store for smoothing continuous oxygen production versus batch oxygen demand.
- Oxygen demand from BF, BOF/OSF, EAF and NG-DRP where source-backed plant coefficients exist.
- Linde Gas as external/interface provider of oxygen, argon, nitrogen and compressed dry air.
- Diagnostic annual oxygen balance and gap reporting.

### Excluded or deferred

- Full Linde ASU unit commitment, cryogenic column dynamics and pressure-level modelling.
- Optimising liquid oxygen or liquid argon back-up inventories.
- Strategic oxygen storage arbitrage against day-ahead prices.
- Nitrogen, argon and compressed dry air as fully modelled utility carriers.
- mFRR from the ASU unless a later dedicated ASU-flexibility source and buffer-deliverability gate is created.

## Recommended topology

```text
electricity_bus -> LINDE_ASU_LINK -> oxygen_bus

oxygen_bus -> BF oxygen demand
oxygen_bus -> BOF/OSF oxygen demand
oxygen_bus -> EAF oxygen demand
oxygen_bus -> NG-DRP oxygen demand

oxygen_bus <-> oxygen_short_buffer
```

The `oxygen_short_buffer` is a physical smoothing buffer, not a large economic battery. In the first
implementation it should be allowed only to absorb intra-process mismatch and should be reported with
low capacity / low flexibility caveats.

## Source hierarchy

| Source ID | Source | Main use | Status |
|---|---|---|---|
| `S1_MER_HERACLESS_B` | Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025). *MER Heracless – Groen Staal, Deel B: Technische beschrijving*. Definitief, 15 September 2025. URL: https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf | Tata-specific oxygen-network, oxygen stations, oxygen buffers, Linde Gas scope, Heracless changes. | Highest topology/source anchor. |
| `S2_LINDE_BENELUX_OXYGEN` | Linde Gas Benelux. *Oxygen*. URL: https://www.linde-gas.nl/shop/en/nl-ig/oxygen | Confirms Linde air gases are produced in IJmuiden on the Tata Steel site and describes air separation process. | Official supplier/source-context evidence. |
| `S3_EIGA_PP033` | European Industrial Gases Association (EIGA). *Indirect CO2 emissions compensation: Benchmark proposal for Air Separation Plants*, Position Paper PP-33. URL: https://www.eiga.eu/uploads/documents/PP033.pdf | ASU electricity benchmark: gaseous oxygen at 40 bar and liquid oxygen. | Best compact ASU electricity benchmark. |
| `S4_LINDE_PDS_O2` | Linde Gas Benelux. *Product Data Sheet Oxygen 2.5*, NL-PIB-0219/6. URL: https://www.linde-gas.nl/wcsstore/NL_RES_Industrial_Gas_Store/PDS/PDS_EN_MS-39373_2021.pdf | Oxygen density and conversion basis. | Official physical-property source. |
| `S5_LINDE_ASU_BROCHURE` | Linde Engineering. *Customised air separation plants*. URL: https://assets.linde.com/-/media/global/engineering/engineering/home/products-and-services/success-stories/perfect-process-technology-for-every-project/customised-air-separation-plants-brochure.pdf | Typical large ASU capacity context and co-production of oxygen, nitrogen and argon. | Supplier context; not Tata-specific. |
| `S6_JRC_IS_BREF` | Remus, R., Aguado-Monsonet, M. A., Roudier, S., Delgado Sancho, L. (2013). *Best Available Techniques Reference Document for Iron and Steel Production*. European Commission JRC. DOI: 10.2791/97469. URL: https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/IS_Adopted_03_2012.pdf | BF, BOF and EAF oxygen-use candidate ranges. | Best generic iron/steel process coefficient source. |
| `S7_TENOVA_ENERGIRON` | Duarte, P. et al. *ENERGIRON Direct Reduction Technology / Environmental emissions compliance and reduction of greenhouse gases in a DR-EAF steel plant*. Tenova / Danieli. URL: https://tenova.com/sites/default/files/2021-09/2008-Environmental-Emissions-Compliance-And-Reduction-Of-Greenhouse-Gases-In-A-DR-EAF-Steel-Plant-2.pdf | NG-DRP oxygen-use cross-check where DRP oxygen is explicitly represented. | Technology/vendor source; not Tata-specific. |
| `S8_ATHANASIADIS_2025` | Athanasiadis, I. (2025). *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel’s IJmuiden Site*. TU Delft MSc thesis. | Modelling precedent: Linde plant as ASU, oxygen store constraint, ~150 t/h site oxygen demand. | Modelling precedent only; not public Tata-truth. |
| `S9_BADARINATH_2025` | Badarinath, M. (2025). *Optimising Industrial Participation in the Day-Ahead Electricity Market*. TU Delft MSc thesis. | Secondary precedent: Linde ASU as large stable electricity consumer and limited flexibility. | Secondary modelling precedent only. |

## Core parameters

| Parameter ID | Value / range | Unit | Status | Source link(s) | Model use / caveat |
|---|---:|---|---|---|---|
| `LINDE_ASU_OUTPUT_BASIS` | gaseous oxygen delivered to site oxygen network | t O2 or Nm3 O2 | modelling choice | `S1_MER_HERACLESS_B`, `S2_LINDE_BENELUX_OXYGEN` | Use a common `oxygen_bus`. Prefer Nm3 for process demand and t O2 for ASU electricity accounting. |
| `LINDE_PRODUCTS_SCOPE` | O2, Ar, N2, compressed dry air | carrier list | topology anchor | `S1_MER_HERACLESS_B` | Only O2 is active in first implementation. Ar, N2 and dry air remain deferred or reporting-only. |
| `LINDE_O2_PRODUCED_AT_IJMUIDEN` | true | bool | source-backed topology | `S2_LINDE_BENELUX_OXYGEN` | Linde says Benelux air gases including gaseous/liquid oxygen are produced in Botlek and IJmuiden on the Tata Steel site. |
| `LINDE_ASU_ELECTRICITY_MWH_PER_T_O2_GAS_BASE` | 0.400 | MWh/t O2 | base candidate | `S3_EIGA_PP033` | EIGA benchmark for gaseous oxygen at 40 bar. Good first compact ASU electricity coefficient. |
| `LINDE_ASU_ELECTRICITY_MWH_PER_T_O2_LIQUID` | 0.638 | MWh/t O2 | sensitivity / backup-production check | `S3_EIGA_PP033` | EIGA benchmark for liquid oxygen. Do not use as base for normal gaseous network supply. |
| `LINDE_ASU_ELECTRICITY_KWH_PER_NM3_O2_GAS_BASE` | 0.572 | kWh/Nm3 O2 | derived candidate | `S3_EIGA_PP033`, `S4_LINDE_PDS_O2` | Derived from 0.400 MWh/t and oxygen density 1.429 kg/Nm3. Useful if plant oxygen demand is in Nm3. |
| `LINDE_O2_DENSITY_KG_PER_NM3` | 1.429 | kg/Nm3 at 1.013 bar, 0 °C | conversion factor | `S4_LINDE_PDS_O2` | Use only for unit conversion. Be explicit about temperature/pressure basis. |
| `LINDE_O2_NM3_PER_T_O2` | 699.8 | Nm3/t O2 | derived conversion | `S4_LINDE_PDS_O2` | `1000 / 1.429`. |
| `LINDE_ASU_CAPACITY_CONTEXT_RANGE` | 1,000–5,500 t O2/day | t O2/day | context / plausibility | `S5_LINDE_ASU_BROCHURE` | Linde customised ASU capacity range; not a Tata-capacity claim. |
| `LINDE_O2_DEMAND_PRECEDENT_T_PER_H` | ~150 | t O2/h | modelling precedent / validation | `S8_ATHANASIADIS_2025`, `S9_BADARINATH_2025` | Useful sanity check only. Do not hard constrain the model to this value without site-approved data. |
| `LINDE_O2_DEMAND_PRECEDENT_NM3_PER_H` | ~105,000 | Nm3 O2/h | derived sanity check | `S4_LINDE_PDS_O2`, `S8_ATHANASIADIS_2025` | Derived from 150 t/h and density 1.429 kg/Nm3. |
| `LINDE_ASU_POWER_AT_150_T_H_O2` | ~60 | MW | derived sanity check | `S3_EIGA_PP033`, `S8_ATHANASIADIS_2025` | `150 t/h * 0.400 MWh/t = 60 MW`. Use as consistency check, not hard capacity. |
| `LINDE_N2_AUXILIARY_ELECTRICITY_CONTEXT_MW` | ~45 | MW | accepted development context / separate site-load diagnostic | `S8_ATHANASIADIS_2025` | Athanasiadis p. 36 models non-steel processes such as N2 as a historical varying Linde electricity load; p. 42 describes about 45 MW unrelated to steel production. Keep separate from O2-specific ASU intensity, material demand and residual electricity. |
| `LINDE_O2_BUFFER_GEOMETRIC_VOLUME_M3` | 20 × 50 + 670 = 1,670 | m3 vessel volume | structural anchor / not model-ready Nm3 capacity | `S1_MER_HERACLESS_B` | Pressurised gaseous oxygen buffer tanks; not cryogenic. Pressure is not public, so do not convert to Nm3 storage capacity without assumption. |
| `LINDE_O2_BUFFER_MODE` | `balancing_buffer_only` | policy | base policy | `S1_MER_HERACLESS_B`, `S8_ATHANASIADIS_2025` | Buffers smooth continuous O2 production against discontinuous BOF converter demand; not a strategic electricity-price storage asset. |
| `LINDE_O2_STRATEGIC_STORAGE_ALLOWED` | false | bool | base policy | `S1_MER_HERACLESS_B`, `S8_ATHANASIADIS_2025` | Prevents fake DA arbitrage through oxygen storage. |
| `LINDE_ASU_MFRR_ELIGIBLE_BASE` | false | bool | base policy | `S1_MER_HERACLESS_B`, `S8_ATHANASIADIS_2025` | No mFRR from ASU in base. Later only if ASU ramp/source evidence and oxygen-buffer deliverability are explicitly implemented. |
| `LINDE_LIQUID_O2_BACKUP_EXPANSION` | true | bool / topology | validation / context | `S1_MER_HERACLESS_B` | Linde expands liquid oxygen buffer capacity for back-up. Do not treat as normal dispatch storage. |
| `LINDE_LIQUID_ARGON_BACKUP_EXPANSION` | true | bool / topology | validation / context | `S1_MER_HERACLESS_B` | Argon remains deferred unless secondary metallurgy is explicitly modelled. |
| `LINDE_NITROGEN_CHANGE_WITH_HERACLESS` | no major change foreseen | qualitative | validation / context | `S1_MER_HERACLESS_B` | Supports a same-order C0/C1 N2 context load, but is not a measured hourly Tata profile. |
| `LINDE_COMPRESSED_DRY_AIR_EXTRA_COMPRESSOR` | 20,000 | Nm3/h | deferred utility anchor | `S1_MER_HERACLESS_B` | Extra compressed dry air compressor; not oxygen. Add later if compressed air is modelled. |

## Process oxygen demand parameters

These rows gather the current source-backed oxygen demand parameters from the plant source cards.
They should be consumed through the common `oxygen_bus`.

| Parameter ID | Value / range | Unit | Status | Source link(s) | Model use / caveat |
|---|---:|---|---|---|---|
| `BF_OXYGEN_INPUT_NM3_PER_T_HM` | base 43; range 4.6–67 | Nm3 O2/t hot metal | base candidate / source range | `S6_JRC_IS_BREF` Table 6.1 | Strong source-backed BF oxygen parameter. Also BREF gives 54.4 kg/t HM weighted average. |
| `BF_OXYGEN_INPUT_KG_PER_T_HM` | base 54.4; range 0–85.1 | kg O2/t hot metal | base candidate / source range | `S6_JRC_IS_BREF` Table 6.1 | Use one unit basis consistently; do not double count kg and Nm3 rows. |
| `BOF_OXYGEN_INPUT_NM3_PER_T_LS` | 49.5–70; base 55–60 | Nm3 O2/t liquid steel | base candidate | `S6_JRC_IS_BREF` Table 7.3 | Strongest BOF/OSF oxygen parameter. Highest priority for oxygen bus. |
| `EAF_OXYGEN_INPUT_NM3_PER_T_LS` | 5–65; base 35 | Nm3 O2/t liquid steel | base candidate / sensitivity | `S6_JRC_IS_BREF` Table 8.1 | Broad range due EAF practice; base 35 is development candidate, not Tata truth. |
| `DRP_OXYGEN_INPUT_NM3_PER_T_DRI` | 35 | Nm3 O2/t DRI | candidate / sensitivity | `S7_TENOVA_ENERGIRON`, `DRP_Parameters.md` | Relevant for NG-DRP Phase 1 only if partial combustion/oxygen addition is explicitly active. |
| `SINTER_OXYGEN_INPUT` | 0 | — | not modelled | `SINTER_Parameters.md`, `S6_JRC_IS_BREF` | No separate oxygen utility demand in first simplified sinter model. |
| `PELLETIZING_OXYGEN_INPUT` | deferred / not base | — | deferred detail | `PELLETIZING_Parameters.md`, `S6_JRC_IS_BREF` | Pellet plant burners may involve oxygen-enriched conditions in some contexts, but first PeFa model uses gas/fuel energy carriers, not explicit oxygen. |
| `COKING_OXYGEN_INPUT` | 0 | — | not modelled | `S1_MER_HERACLESS_B`, coking source card | Coke making occurs without oxygen in the coke chamber; combustion air for heating is not pure O2 utility demand. |
| `HSM_OXYGEN_INPUT` | 0 | — | not modelled | `HSM_Parameters.md` | HSM is reheating/rolling energy consumer; no separate O2 demand in first model. |
| `DSP_OXYGEN_INPUT` | 0 | — | not modelled | `DSP_Parameters.md` | No source-backed O2 input in first simplified DSP model. |
| `SECONDARY_METALLURGY_ARGON_NITROGEN` | deferred | Nm3/t LS | deferred detail | `S1_MER_HERACLESS_B`, `S6_JRC_IS_BREF` Table 7.3 | BOF BREF gives argon and nitrogen use; secondary metallurgy gas treatment is deferred. |

## Derived annual oxygen sanity checks

These are **validation diagnostics**, not constraints.

| Diagnostic ID | Formula | Approximate value | Status | Caveat |
|---|---|---:|---|---|
| `C0_BF_O2_MNM3_Y` | 6.3 Mt HM/y × 43 Nm3/t HM | ~271 MNm3/y | derived validation | Uses C0 HM anchor and BREF BF O2. |
| `C0_BOF_O2_MNM3_Y` | 7.2 Mt LS/y × 55 Nm3/t LS | ~396 MNm3/y | derived validation | Uses BOF base 55. |
| `C0_CORE_O2_MNM3_Y` | BF + BOF | ~667 MNm3/y | derived validation | Excludes secondary metallurgy and other site O2 uses. |
| `C0_CORE_O2_KT_Y` | 667 MNm3/y × 1.429 kg/Nm3 / 1000 | ~953 kt/y | derived validation | Equivalent average ~109 t/h. |
| `C1_BF_O2_MNM3_Y` | 2.8 Mt HM/y × 43 Nm3/t HM | ~120 MNm3/y | derived validation | Retained BF6 route only. |
| `C1_BOF_O2_MNM3_Y` | 3.4 Mt LS/y × 55 Nm3/t LS | ~187 MNm3/y | derived validation | Retained BF-BOF route only. |
| `C1_EAF_O2_MNM3_Y` | 3.3 Mt LS/y × 35 Nm3/t LS | ~116 MNm3/y | derived validation | EAF oxygen broad uncertainty. |
| `C1_DRP_O2_MNM3_Y` | 2.8 Mt DRI/y × 35 Nm3/t DRI | ~98 MNm3/y | derived validation | Only if DRP O2 is active. |
| `C1_CORE_O2_MNM3_Y` | BF + BOF + EAF + DRP | ~521 MNm3/y | derived validation | Excludes secondary metallurgy and other site uses. |
| `C1_CORE_O2_KT_Y` | 521 MNm3/y × 1.429 kg/Nm3 / 1000 | ~744 kt/y | derived validation | Equivalent average ~85 t/h. |

The derived oxygen balances are intentionally below the modelling-precedent `~150 t/h` site demand because
they include only the explicitly modelled core process uses. Any gap should be reported as
`oxygen_residual_or_unmodelled_uses`, not hidden inside a plant coefficient.

## Recommended first implementation equations

```text
oxygen_demand[t] =
    BF_hot_metal[t] * BF_OXYGEN_INPUT_NM3_PER_T_HM
  + BOF_liquid_steel[t] * BOF_OXYGEN_INPUT_NM3_PER_T_LS
  + EAF_liquid_steel[t] * EAF_OXYGEN_INPUT_NM3_PER_T_LS
  + DRP_DRI[t] * DRP_OXYGEN_INPUT_NM3_PER_T_DRI
  + oxygen_residual_diagnostic[t]

oxygen_production_t_O2[t] =
    oxygen_production_Nm3[t] * 1.429 / 1000

LINDE_ASU_electricity_MWh[t] =
    oxygen_production_t_O2[t] * 0.400
```

If the oxygen store is activated:

```text
oxygen_store[t+1] =
    oxygen_store[t]
  + oxygen_production_Nm3[t]
  - oxygen_demand_Nm3[t]

oxygen_store_capacity_Nm3 = deferred unless pressure is source-backed
```

The known geometric buffer volume is **not** enough to define model-ready Nm3 storage capacity, because the public source does not provide operating pressure and usable pressure swing.

## Anchors

### Long-term/full-model anchors

| Anchor | Value / target | Use |
|---|---:|---|
| Linde supplies O2, Ar, N2 and compressed dry air to Tata Steel | qualitative | utility-boundary validation |
| O2 network with stations across Tata site | qualitative | topology validation |
| Pressurised O2 buffer vessels | 20 × 50 m3 + 670 m3 | short-buffer topology validation |
| Liquid oxygen buffer expansion | qualitative | back-up-position validation |
| Site oxygen demand precedent | ~150 t/h | high-level sanity check only |
| ASU electricity at 150 t/h with EIGA gaseous O2 benchmark | ~60 MW | ASU electricity sanity check |
| C0 core process oxygen | ~953 kt/y, ~109 t/h | modelled-core balance check |
| C1 core process oxygen | ~744 kt/y, ~85 t/h | modelled-core balance check |
| Extra compressed dry air compressor | 20,000 Nm3/h | deferred dry-air utility anchor |

### Small first-implementation checks

| Check | Use |
|---|---|
| `oxygen_balance_gap` | detect missing plant oxygen demand or overproduction |
| `oxygen_store_boundary_hits` | prevent oxygen buffer acting as large battery |
| `ASU_electricity_MWh` | full-site electricity accounting |
| `Linde_N2_auxiliary_electricity_MWh` | explicit non-steel site-context load, separately reported |
| `Linde_total_meter_electricity_MWh` | O2-process electricity plus explicit N2/auxiliary context load |
| `ASU_average_MW` | compare against high-level ASU demand precedent |
| `oxygen_residual_or_unmodelled_uses` | report gap to site-level oxygen precedent |
| `O2_demand_by_plant` | identify whether BF/BOF/EAF/DRP dominate |

## Caveats

1. The Linde oxygen system should not be used as a strategic DA-flexibility asset in the first model.
2. The public oxygen buffer information gives vessel volume, not usable gas storage in Nm3.
3. Oxygen demand is well-supported for BF, BOF and EAF; DRP oxygen is technology-supported but should remain sensitivity until the NG-DRP process-gas oxygen convention is locked.
4. The `~150 t/h` Linde demand is a modelling precedent and high-level sanity anchor, not a hard public Tata source.
5. Derived C0/C1 core oxygen totals are incomplete by design: secondary metallurgy, maintenance, purging, backup, distribution losses and non-modelled users are not fully included.
6. Avoid double counting oxygen from both kg/t and Nm3/t source rows. Choose one canonical unit convention and convert explicitly.
7. If liquid oxygen back-up is represented, keep it separate from normal gaseous ASU production and label it as reliability/back-up, not dispatchable economic storage.
8. The ~45 MW N2/auxiliary value is a public Athanasiadis model-precedent context load, not a public Tata meter trace. It may be used in a labelled development boundary diagnostic, but must not be converted into O2 demand, a plant fuel split, a residual plug or a price-responsive flexibility resource.
