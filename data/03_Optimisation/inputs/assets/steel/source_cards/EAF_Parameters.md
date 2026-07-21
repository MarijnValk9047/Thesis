# Electric Arc Furnace / EAF Parameters — heat-state and flexibility source-card memo

## Status

This note records a compact, source-backed candidate parameter set and modelling design for the Tata Steel IJmuiden-inspired Electric Arc Furnace (`EAF`) in the C1 Phase 1 DRP-EAF route.

It is a **candidate/source-card memo**, not an executable input table and not thesis-approved truth.

Rows below must be migrated through the normal workflow before model use:

```text
source -> source card -> candidate evidence -> assumption/register row -> reviewed development input -> executable model input
```

## Scope and modelling intention

The EAF is the main electricity-intensive flexible plant in the future C1 steel configuration. Unlike the BF, KGF, BOF, Sinter and Pelletizing Plant, the EAF must not be represented as a smooth continuously dimmable load. It is a batch process operating in heats.

Preferred activity basis for source-card parameters:

```text
P_EAF[t] = liquid_steel_output[t]      # t liquid steel / time step
```

For the optimisation model, the EAF should be represented with **fixed heat states** from the start, even in deterministic DA-only models without mFRR. The same heat-state structure then becomes the physical basis for mFRR deliverability.

Key modelling choice:

```text
EAF_HEAT_SIZE_T_LS = 325 t liquid steel / heat
```

A heat-state model is active for production scheduling and energy accounting. mFRR variables are optional add-ons; the heat-state model itself is not an mFRR-only extension.

## Source hierarchy

| Rank | Source | Main use | Reliability / caveat |
|---:|---|---|---|
| 1 | Haskoning Nederland B.V. / Tata Steel IJmuiden B.V. (2025), *MER Heracless - Groen Staal, Deel B: Technische beschrijving* | Tata-specific EAF process topology, batch description, DRI/scrap/liquid-steel anchors, heat size, hot heel, Consteel/scrap preheating, EAF off-gas treatment. | High for public Tata topology and technical description. Does not give a full optimisation-ready heat schedule. |
| 2 | Royal HaskoningDHV / Tata Steel IJmuiden B.V. (2025), *MER Heracless - Detailstudie Energie en CO2-balans* | EAF energy balance, average EAF production rate, EAF electricity, off-gas heat recovery, steam production, off-gas temperatures, secondary metallurgy electricity and steam. | Strong public technical source, but many values are design/vendor-based and scenario-specific. |
| 3 | Remus, R., Aguado-Monsonet, M. A., Roudier, S., & Delgado Sancho, L. (2013), *Best Available Techniques (BAT) Reference Document for Iron and Steel Production*, European Commission JRC, Chapter 8 Electric Arc Furnace Steelmaking and Casting | Generic EAF material, energy, CO2, slag and off-gas ranges. | High-authority generic technical range. Not Tata-specific and mostly scrap-EAF oriented. |
| 4 | Boldrini, A., Koolen, D., Crijns-Graus, W. H. J., & van den Broek, M. (2024), *Flexibility options in a decarbonising iron and steel industry* | EAF demand-response framing and the 30-minute interruption caveat, citing Paulus et al. | High for flexibility literature review. The 30-minute rule is generic and should be a guardrail, not a Tata-validated control-room rule. |
| 5 | Paulus, M., & Borggrefe, F. (2011), *The potential of demand-side management in energy-intensive industries for electricity markets in Germany* | Original DSM source cited for EAF interruption behaviour. | Generic DSM literature; use through Boldrini unless exact original table is separately reviewed. |
| 6 | Athanasiadis, I. (2025), *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site* | PyPSA modelling precedent for EAF as a committable batch unit; one decision variable per process/link; DRP-EAF route modelling. | Modelling precedent only. Not an exact public Tata parameter source. |
| 7 | Badarinath, M. (2025), *Optimising Industrial Participation in the Day-Ahead Electricity Market* | Secondary precedent for semi-continuous EAF formulation, DRI-buffer decoupling and bidding experiments. | Secondary modelling precedent; not a physical source-card for EAF heat-cycle truth. |

## Compact process representation

```text
HDRI + scrap + electricity + oxygen + carbon/coal + fluxes + electrodes + NG
    -> liquid_steel + EAF_slag + EAF_offgas + CO2
```

EAF off-gas is **not** treated as WAG in the same sense as BFG, COG or BOFG. It is an off-gas / waste-heat stream. The first useful recovery path is:

```text
EAF_offgas_heat -> scrap_preheating + steam_recovery
```

The off-gas should therefore not be added as a new dispatchable WAG fuel carrier.

## Selected heat-state modelling approach

### Chosen approach: fixed heat-block state model

Use fixed 325 t liquid-steel heats and a simple quarter-hour heat-state skeleton:

```text
1 heat = 325 t LS
normal heat duration = 3 quarter-hour steps = 45 min

state sequence:
  q0: MELTING_POWER_ON_1
  q1: MELTING_POWER_ON_2
  q2: TAPPING_TURNAROUND_POWER_OFF
```

Rationale:

- The MER gives a heat size of approximately 325 t liquid steel per tap.
- The energy-detail study gives a design/average production rate of 458 t LS/h for the EAF energy balance. The implied heat duration is `325 / 458 = 0.71 h = 42.6 min`, which is well approximated by a 45-minute / three-quarter-hour block.
- The MER says that the EAF works in batches and that, over a cycle, arc power is ramped in steps while DRI, scrap and additives are fed; at the end, the electrodes are withdrawn, the arc stops and steel is tapped. A three-step state model is therefore consistent with the public description while remaining tractable.

### Why this works without mFRR

In deterministic DA-only or stochastic DA-only models, the heat-state model simply determines when electricity is consumed and when liquid steel is released:

```text
heat_start[q]                -> creates two power-on melting quarters
liquid_steel_output[q + 2]   = heat_start[q] * EAF_HEAT_SIZE_T_LS
EAF_electricity[q or q+1]    = heat electricity allocated over the two melting quarters
```

No reserve variables are needed. The model can still schedule heats, DRI drawdown, scrap use, liquid-steel output and downstream coupling.

### How mFRR is added later

mFRR capacity may only be offered during `MELTING_POWER_ON` states. It is not available during tapping/turnaround or idle periods.

```text
mFRR_up_capacity[q] <= available_arc_load[q]
available_arc_load[q] > 0 only when EAF_state[q] == MELTING_POWER_ON
```

If an mFRR activation reduces or interrupts EAF arc power, the missed electrical energy must be made up by extending the heat with additional melting time. Because this memo deliberately excludes power increases above the normal maximum, energy recovery cannot be achieved by running at 125% power.

```text
EAF_POWER_RATE_MAX_REL = 1.00
missing_heat_energy_MWh must be recovered by extra MELTING_POWER_ON time
```

### Explicitly excluded flexibility

Do **not** include a 125% over-power option in the base case or sensitivity set.

The earlier literature review noted that some studies investigate higher power rates, but this source card deliberately excludes that mechanism because it would add unverified electrode/equipment degradation and could create too much artificial upward recovery after reserve activation.

## Heat-state and flexibility parameters

| Parameter ID | Unit | Range / value | Most likely / selected | Status | Source and locator | Model role and caveat |
|---|---:|---:|---:|---|---|---|
| `EAF_HEAT_STATE_MODEL_ACTIVE` | bool | true | true | modelling policy | MER Deel B Ch.11; Athanasiadis EAF committable batch precedent | Heat states active in DA-only and mFRR models. Not an mFRR-only feature. |
| `EAF_OUTPUT_BASIS` | t LS | liquid steel | liquid steel | modelling choice | MER Deel B Ch.11 | Primary output basis. |
| `EAF_HEAT_SIZE_T_LS` | t LS/heat | approx. 325 | 325 | base candidate | MER Deel B §11.1 and Energy & CO2 study §5.4.1 | Fixed production block per heat. |
| `EAF_DESIGN_LS_RATE_T_PER_H` | t LS/h | 458 | 458 | validation / design-rate candidate | Energy & CO2 study Table 5.1 note | Used only to derive a plausible heat duration. Not an annual capacity target. |
| `EAF_HEAT_DURATION_MIN_DERIVED` | min/heat | 42.6 | round to 45 | derived value | `325 t / 458 t/h` | Round to three 15-minute intervals for tractability. |
| `EAF_HEAT_QH_STEPS_TOTAL` | quarter-hours/heat | 3 | 3 | modelling choice | Derived from previous row | QH heat skeleton. |
| `EAF_MELTING_QH_STEPS_BASE` | quarter-hours/heat | 2 | 2 | modelling assumption | MER says arc power is used during cycle and stops before tapping | Two 15-minute power-on intervals. Development assumption, not a measured Tata sequence. |
| `EAF_TAPPING_TURNAROUND_QH_STEPS_BASE` | quarter-hours/heat | 1 | 1 | modelling assumption | MER says electrodes are withdrawn and arc stops before tapping | One power-off quarter for tapping/turnaround. |
| `EAF_POWER_ON_STATE_LABELS` | set | `MELTING_POWER_ON_1`, `MELTING_POWER_ON_2` | same | modelling choice | MER Ch.11 | Only these states can carry arc load and mFRR up-capacity. |
| `EAF_POWER_OFF_STATE_LABELS` | set | `TAPPING_TURNAROUND`, `IDLE`, `MAINTENANCE` | same | modelling choice | MER Ch.11 | No EAF arc-load mFRR capacity in these states. |
| `EAF_REFINING_RESERVE_ALLOWED_BASE` | bool | false | false | conservative guardrail | Völkl process-state literature; general EAF quality caveat | Do not count refining/chemistry/temperature-quality stage as reliable reserve until explicitly modelled. |
| `EAF_POWER_RATE_MAX_REL` | fraction of normal max | 1.00 | 1.00 | hard modelling policy | User decision + equipment-caveat logic | Explicitly excludes 125% over-power. Missed energy extends heat instead. |
| `EAF_MELTING_POWER_REL_MIN_IF_ON` | fraction of normal melting power | 0.60-1.00 | 0.60 | development candidate | EAF flexibility literature uses reduced power-rate cases; treat as generic | Minimum non-paused melting power if modulation rather than full interruption is used. Not Tata-validated. |
| `EAF_PAUSE_ALLOWED_DURING_MELTING` | bool | true | true | base flexibility rule | Boldrini et al. review, citing Paulus et al. | Short interruptions only during power-on melting states. |
| `EAF_PAUSE_ALLOWED_DURING_TAPPING` | bool | false | false | base flexibility rule | MER Ch.11 process description | Arc is already stopped; no useful arc-load reduction. |
| `EAF_PAUSE_ALLOWED_DURING_IDLE` | bool | false | false | base flexibility rule | modelling logic | No load exists to reduce. |
| `EAF_INTERRUPT_MAX_CONTIGUOUS_MIN_BASE` | min | 15 | 15 | conservative base candidate | One Dutch ISP / QH step; below 30-min hard caveat | Use one 15-minute mFRR activation as base. |
| `EAF_INTERRUPT_MAX_CONTIGUOUS_MIN_HARD` | min | 30 | 30 | hard guardrail | Boldrini et al. state that >30 min interruption forces restart, citing Paulus et al. | Above this, heat is infeasible or must be restarted; do not hide with slack. |
| `EAF_INTERRUPT_MAX_QH_HARD` | quarter-hours | 2 | 2 | derived guardrail | `30 min / 15 min` | Maximum two consecutive interrupted QH intervals before restart logic. |
| `EAF_MISSED_ENERGY_MAKEUP_REQUIRED` | bool | true | true | hard modelling policy | physical energy balance | Curtailed energy must be made up before tapping/output release. |
| `EAF_MAKEUP_MODE` | policy | `extend_heat_no_overpower` | `extend_heat_no_overpower` | selected policy | User decision excluding 125% | Add extra melting time; do not boost later power above 1.0. |
| `EAF_OUTPUT_RELEASE_STATE` | state | after tapping/turnaround | after `TAPPING_TURNAROUND` | modelling choice | MER Ch.11 | Liquid steel becomes available only after tap state. |
| `EAF_MFRR_UP_ALLOWED_BASE` | bool | true, only during melting | true | base mFRR policy | Boldrini/Paulus + MER heat-state logic | Upward reserve means load reduction from active arc load. |
| `EAF_MFRR_DOWN_ALLOWED_BASE` | bool | false | false | base mFRR policy | conservative | Downward reserve would require running below max before activation and possibly increasing power; deferred. |
| `EAF_MFRR_UP_CAPACITY_SHARE_RATED_BASE` | fraction rated MW | 0.20 | 0.20 | aggregate fallback | Generic EAF reserve literature / Boldrini review context | Use only if not using explicit heat-state arc load. |
| `EAF_MFRR_UP_CAPACITY_SHARE_RATED_HIGH` | fraction rated MW | 0.40 | 0.40 | sensitivity / aggregate fallback | Generic EAF reserve literature / Boldrini review context | Upper aggregate fallback, not heat-state preferred. |

## Core EAF material and energy parameters

| Parameter ID | Unit | Range / value | Most likely / selected | Status | Source and locator | Model role and caveat |
|---|---:|---:|---:|---|---|---|
| `EAF_C1_LS_ANNUAL_OUTPUT_MT` | Mt LS/y | approx. 3.3 | 3.3 | validation anchor | MER Deel B §11.1 | EAF route liquid-steel output; anchor, not hourly constraint. |
| `EAF_HDRI_INPUT_T_PER_T_LS` | t HDRI/t LS | `2.8 / 3.3` | 0.848 | derived base candidate | MER Deel B §11.1: 2.8 Mt HDRI and 3.3 Mt LS | DRI-to-EAF material coupling. Depends on DRI quality and yield simplification. |
| `EAF_SCRAP_INPUT_T_PER_T_LS` | t scrap/t LS | `~1.0 / 3.3` | 0.303 | derived base candidate | MER Deel B §11.1: about 1 Mt scrap and 3.3 Mt LS | Scrap input candidate. Rounded source value; not exact recipe. |
| `EAF_ELECTRICITY_MWH_PER_T_LS_TATA` | MWh/t LS | `1.52 GJ/t / 3.6` | 0.422 | Tata-specific base candidate | Energy & CO2 study Table 5.1 | EAF arc/electricity in vlamboogoven energy balance. Does not include all site electricity or all secondary metallurgy. |
| `EAF_ELECTRICITY_MWH_PER_T_LS_PROJECT_PRECEDENT` | MWh/t LS | 0.525 | 0.525 | sensitivity / previous-project value | Existing project precedent and within BREF range | Use only with clear basis; do not mix with Tata 0.422 without reporting. |
| `EAF_ELECTRICITY_MWH_PER_T_LS_BREF_RANGE` | MWh/t LS | 0.404-0.748 | not selected | external benchmark | JRC BREF Table 8.1 | Generic EAF range, mostly scrap-EAF oriented. |
| `EAF_ARC_ENERGY_MWH_PER_HEAT_TATA` | MWh/heat | `325 * 0.422` | 137 | derived | From `EAF_HEAT_SIZE_T_LS` and `EAF_ELECTRICITY_MWH_PER_T_LS_TATA` | Heat-level electricity requirement. |
| `EAF_ARC_POWER_MW_PER_ACTIVE_HEAT_TATA` | MW/active heat | `137 MWh / 0.5 h` | 274 | derived | Two QH power-on intervals | Arc-load during melting state if energy is allocated over two QH intervals. Derived, not a nameplate rating. |
| `EAF_AVG_POWER_MW_ENERGY_STUDY` | MW | 200 MWe for furnace + few MWe auxiliaries | 200 | validation anchor | Energy & CO2 study §5.3.2 | Energy-study average over hour at design production. Useful sanity check. |
| `EAF_HDRI_SENSIBLE_CHEMICAL_GJ_PER_T_LS` | GJ/t LS | 1.28 | 1.28 | base energy-balance component | Energy & CO2 study Table 5.1 | Heat/chemical energy carried by HDRI. Reporting/diagnostic unless full thermal balance active. |
| `EAF_SCRAP_HEAT_GJ_PER_T_LS` | GJ/t LS | 0.14 | 0.14 | base energy-balance component | Energy & CO2 study Table 5.1 | Scrap preheat contribution. |
| `EAF_COKE_BREEZE_ANTHRACITE_GJ_PER_T_LS` | GJ/t LS | 0.27 | 0.27 | base candidate / carbon driver | Energy & CO2 study Table 5.1 | Less than 10% of energy input; mainly slag foaming. |
| `EAF_ELECTRODES_GJ_PER_T_LS` | GJ/t LS | 0.03 | 0.03 | base candidate / cost-carbon detail | Energy & CO2 study Table 5.1 | Electrode consumption energy-equivalent. |
| `EAF_NG_GJ_PER_T_LS` | GJ/t LS | 0.05 | 0.05 | base candidate / auxiliary fuel | Energy & CO2 study Table 5.1; MER §11.1 oxyfuel burner | NG used in oxyfuel burners / oxygen lances. |
| `EAF_TOTAL_ENERGY_IN_GJ_PER_T_LS` | GJ/t LS | 3.30 | 3.30 | validation check | Energy & CO2 study Table 5.1 | Check only; avoid double-counting if separate components are active. |
| `EAF_OXYGEN_INPUT_NM3_PER_T_LS_BREF` | Nm3/t LS | 5-65 | 35 if needed | source range / development midpoint | JRC BREF Table 8.1 | Keep as broad range unless Linde/oxygen layer requires a point. |
| `EAF_COAL_KG_PER_T_LS_BREF` | kg/t LS | 3-28 | deferred | source range | JRC BREF Table 8.1 | Carbon/slag foaming cross-check against Tata 0.27 GJ/t. |
| `EAF_ELECTRODES_KG_PER_T_LS_BREF` | kg/t LS | 2-6 | deferred | source range | JRC BREF Table 8.1 | Cost/carbon detail; not first flexibility driver. |
| `EAF_LIME_DOLOMITE_KG_PER_T_LS_BREF` | kg/t LS | 25-140 | deferred | source range | JRC BREF Table 8.1 | Flux/slag detail; defer unless slag chemistry is active. |
| `EAF_DIRECT_CO2_T_PER_T_LS_BREF` | tCO2/t LS | 0.072-0.180 | range only | emissions range / validation | JRC BREF Table 8.1 | Do not combine blindly with explicit fuel-derived CO2. |
| `EAF_SLAG_KG_PER_T_LS_BREF` | kg/t LS | 60-270 | range only | by-product range | JRC BREF Table 8.1 | EAF slag validation. |
| `EAF_OFFGAS_NM3_PER_T_LS_BREF` | Nm3/t LS | 8000-10000 | range only | reporting / emissions | JRC BREF Table 8.1 | Off-gas, not WAG. |
| `EAF_SECONDARY_MET_ELECTRICITY_MWH_PER_T_LS` | MWh/t LS | 0.023-0.042 | 0.031 | linked downstream parameter | Energy & CO2 study §5.4.2; MER Deel B §11.5 gives similar order | Ladle furnace / secondary metallurgy electricity. Keep separate from EAF arc electricity. |
| `EAF_SECONDARY_MET_STEAM_T_PER_H_PER_DEGASSER` | t steam/h | 17 | 17 | linked downstream parameter | Energy & CO2 study §5.4.1 and §5.4.2 | RH degasser steam demand; not EAF arc-process steam. |

### 2026-07-16 Gate-2 scrap-boundary resolution

MER Deel B Table 5.2 is the governing central-case locator. It reports 0.9
Mt/y EAF scrap at 3.3 Mt/y EAF liquid steel, so the central material coefficient
is `0.9 / 3.3 = 0.272727273 t scrap/t liquid steel`. The approximately 1.0-Mt/y
statement in Section 11.1 is rounded process-description context and is not the
more precise central route ledger.

The 0.9-1.8-Mt/y EAF range and 1.9-2.8-Mt/y site range are operational
high-scrap variants in which scrap replaces DRI while liquid-steel production
does not increase. They are not technical EAF melt-capacity additions. For the
active central rolling case, 1.9 Mt/y is therefore a site supply boundary;
1.0 Mt/y BOF and 1.8 Mt/y EAF remain separate consumer guardrails. Their sum is
deliberately above the site boundary, so the same 1.9-Mt/y allowance is not
reapplied as two route allocations or used to fix the BOF/EAF production split.

## EAF off-gas heat recovery parameters

| Parameter ID | Unit | Range / value | Most likely / selected | Status | Source and locator | Model role and caveat |
|---|---:|---:|---:|---|---|---|
| `EAF_OFFGAS_AS_WAG` | bool | false | false | hard modelling policy | MER off-gas treatment + project WAG ontology | EAF off-gas is heat recovery / emissions stream, not a reusable WAG fuel. |
| `EAF_SCRAP_PREHEAT_ENABLED` | bool | true | true | topology candidate | MER Deel B §11.1; Energy & CO2 study §5.3.1.4 | Consteel-like continuous feed preheats scrap. |
| `EAF_SCRAP_PREHEAT_TEMP_C` | °C | 300-350 | 325 | Tata-specific candidate | Energy & CO2 study §5.3.1.4 | Scrap preheat temperature from EAF process gases. |
| `EAF_OFFGAS_TEMP_AFTER_CONSTEEL_C` | °C | 1100 average; 1300 peak | 1100 average | Tata-specific candidate | Energy & CO2 study §5.3.1.4 | Off-gas after horizontal feed system. |
| `EAF_OFFGAS_COOL_TO_IRECOVERY_C` | °C | 580 average; 750 peak | 580 average | Tata-specific candidate | Energy & CO2 study §5.3.1.4 | Gas cooled before iRecovery/economizer. |
| `EAF_OFFGAS_STACK_TEMP_AFTER_IRECOVERY_C` | °C | approx. 230 | 230 | Tata-specific candidate | Energy & CO2 study §5.3.1.4 | Off-gas cooled after waste-heat boiler/economizer. |
| `EAF_STEAM_OUTPUT_T_PER_H_NG_SCENARIO` | t/h | 38 | 38 | validation / candidate | Energy & CO2 study §5.3.1.4 | Steam output at average production in NG-DRI scenario. |
| `EAF_STEAM_OUTPUT_T_PER_H_H2_SCENARIO` | t/h | 32 | 32 | sensitivity / candidate | Energy & CO2 study §5.3.1.4 | Steam output in hydrogen-rich DRI scenario. |
| `EAF_STEAM_OUTPUT_T_PER_T_LS_NG_DERIVED` | t steam/t LS | `38 / 458` | 0.083 | derived check | Steam output and 458 t/h production basis | Use as derived sanity check, not independent source value. |
| `EAF_STEAM_OUTPUT_T_PER_T_LS_H2_DERIVED` | t steam/t LS | `32 / 458` | 0.070 | derived check | Steam output and 458 t/h production basis | Sensitivity check. |
| `EAF_STEAM_PRESSURE_BAR_G` | bar(g) | 16 | 16 | candidate | Energy & CO2 study §5.3.1.4 | Steam quality from iRecovery. |
| `EAF_STEAM_TEMP_C` | °C | 204 | 204 | candidate | Energy & CO2 study §5.3.1.4 | Steam quality from iRecovery. |
| `EAF_OFFGAS_STEAM_RECOVERY_MWH_TH_PER_T_LS` | MWhth/t LS | 0.076 | 0.076 | candidate / validation | Energy & CO2 study Table 5.2 | Steam production in iRecovery: 76 kWh/t. |
| `EAF_OFFGAS_HEAT_COOLING_MWH_TH_PER_T_LS` | MWhth/t LS | 0.117 | 0.117 | validation / deferred | Energy & CO2 study Table 5.2 | Heat cooled before iRecovery. Not a dispatchable heat source in first model. |
| `EAF_OFFGAS_STACK_LOSS_MWH_TH_PER_T_LS` | MWhth/t LS | 0.031 | 0.031 | validation / deferred | Energy & CO2 study Table 5.2 | Remaining flue-gas loss. |

## Suggested mathematical skeleton

### Quarter-hour heat-state skeleton

For quarter-hour set `Q`, with `Δ = 0.25 h`:

```text
heat_start[q]        integer >= 0   # number of 325 t heats starting in quarter-hour q
heat_melting[q]      integer >= 0
heat_tapping[q]      integer >= 0
heat_completed[q]    integer >= 0

heat_melting[q]   = heat_start[q] + heat_start[q-1] + heat_makeup_melting[q]
heat_tapping[q]   = heat_start[q-2]    # in the no-interruption base schedule
heat_completed[q] = heat_tapping[q]

liquid_steel_output[q] = heat_completed[q] * EAF_HEAT_SIZE_T_LS
```

Normal arc electricity without mFRR activation:

```text
EAF_arc_energy_per_heat_MWh = EAF_HEAT_SIZE_T_LS * EAF_ELECTRICITY_MWH_PER_T_LS_TATA
EAF_arc_power_per_active_heat_MW = EAF_arc_energy_per_heat_MWh / (EAF_MELTING_QH_STEPS_BASE * Δ)

EAF_arc_power[q] = heat_melting[q] * EAF_arc_power_per_active_heat_MW
```

### mFRR extension

When mFRR is activated, reduce arc power only in melting states:

```text
0 <= EAF_mFRR_up_activation_MW[q] <= EAF_arc_power[q]
EAF_mFRR_up_activation_MW[q] = 0 if heat_melting[q] = 0
```

Missed energy:

```text
missed_energy_MWh[q] = EAF_mFRR_up_activation_MW[q] * Δ
```

Recovery without over-power:

```text
heat_makeup_melting[q_future] must supply the cumulative missed_energy_MWh
EAF_POWER_RATE_MAX_REL = 1.00
```

This means reserve activation delays heat completion unless there is already schedule slack. The model should report heat delays, downstream steel-output delays, DRI-buffer effects and any production shortfall risk.

### Hourly DA-only fallback

If the first DA-only model remains hourly and heat states are too heavy, use an internal quarter-hour EAF scheduling layer and aggregate the electricity to hourly settlement:

```text
EAF_hourly_energy[h] = sum_{q in h} EAF_arc_power[q] * 0.25
```

If even that is too large, use a temporary `heat_equivalent_hourly` variable for DA-only smoke tests, but do not use that relaxed version for mFRR claims.

## Flexibility interpretation

| Action | Allowed state | Base treatment | Consequence |
|---|---|---|---|
| Delay heat start | Before `MELTING_POWER_ON_1` | Allowed if DRI/scrap/downstream constraints remain feasible | Best DA-shifting mechanism. No heat damage because the heat has not started. |
| Reduce arc power | `MELTING_POWER_ON` | Allowed down to selected minimum if active | Heat duration extends unless the model had slack. |
| Fully pause arc | `MELTING_POWER_ON` | Allowed for one 15-minute interval in base; hard maximum two consecutive QH intervals | Missed energy must be made up; if >30 minutes, heat restart/infeasible flag. |
| Increase power above normal maximum | None | Not allowed | 125% over-power deliberately excluded. |
| Offer upward mFRR | `MELTING_POWER_ON` only | Allowed, limited by current arc load and interruption guardrails | Must preserve heat completion and downstream feasibility. |
| Offer downward mFRR | Deferred | Not allowed in base | Would require operating below maximum and then increasing; reopened later only. |
| Use tapping period as reserve | `TAPPING_TURNAROUND` | Not allowed | Arc is off; no load to reduce. |
| Use idle period as reserve | `IDLE` | Not allowed | No load exists. |

## Validation anchors

### Long-term / full-model anchors

| Anchor | Value | Use | Source |
|---|---:|---|---|
| C1 EAF liquid steel output | approx. 3.3 Mt/y | EAF route production validation | MER Deel B §11.1 |
| C1 HDRI to EAF | max. 2.8 Mt/y | DRP -> EAF coupling validation | MER Deel B §11.1 |
| C1 scrap to EAF | approx. 1.0 Mt/y | Scrap/yield validation | MER Deel B §11.1 |
| Tap size | approx. 325 t LS/tap | Heat-count validation | MER Deel B §11.1; Energy & CO2 study §5.4.1 |
| EAF energy-balance production basis | 458 t LS/h | Design-rate sanity check | Energy & CO2 study Table 5.1 note |
| EAF average electric power | 200 MWe + few MWe auxiliaries | Electricity sanity check | Energy & CO2 study §5.3.2 |
| EAF off-gas steam output | 38 t/h NG scenario; 32 t/h H2-rich scenario | Steam recovery validation | Energy & CO2 study §5.3.1.4 |
| Full-site additional grid import | about 10 PJ/y | full-site electricity plausibility | MER Deel B §5.5 / energy-system sections |

### Small EAF implementation checks

| Check | Target / use |
|---|---|
| number of heats | `annual LS output / 325 t` |
| liquid steel output | main activity |
| HDRI consumption | DRP/EAF coupling |
| scrap consumption | scrap/yield logic |
| arc electricity | `EAF_ELECTRICITY_MWH_PER_T_LS * LS output` |
| active heat states | no EAF electricity outside melting states |
| tap states | liquid steel released after tapping/turnaround |
| mFRR availability | non-zero only during melting states |
| missed-energy makeup | reserve activations delay or extend heats |
| direct CO2 | fuel-derived or BREF-range validation |
| off-gas steam | reporting / steam-balance validation |

## CO2 handling

Two modes are possible. Do not mix them without reconciliation.

### Aggregate EAF direct-emission mode

```text
EAF_direct_CO2[t] = liquid_steel_output[t] * EAF_DIRECT_CO2_T_PER_T_LS
```

Use the JRC BREF range `0.072-0.180 tCO2/t LS` only as a generic direct-emission range. This is useful for early reporting, but it is not Tata-specific.

### Fuel-explicit mode

```text
EAF_CO2[t] =
    CO2_from_NG_oxyfuel[t]
  + CO2_from_coke_breeze_anthracite[t]
  + CO2_from_electrodes[t]
  + other_direct_process_CO2[t]
```

In this mode, the BREF direct-emission range is a validation target only and must not be added as a separate extra CO2 output.

## Deferred details

The first heat-state model should not include:

- 125% over-power or other above-normal power recovery;
- detailed electrode degradation penalties;
- exact voltage/current/transformer tap modelling;
- detailed heat chemistry, nitrogen pickup or slag chemistry;
- grade/recipe-dependent secondary metallurgy routing;
- sequence-dependent ladle/caster constraints;
- exact Tata operating calendars and maintenance schedules;
- full sub-minute EAF load fluctuations;
- detailed water-cooling and off-gas filter electricity;
- dispatchable use of EAF off-gas as WAG.

## Source cards / full references

### S1 — MER Heracless / Tata-specific EAF topology and anchors

**Title:** *MER Heracless - Groen Staal, Deel B: Technische beschrijving*
**Organisation / client:** Haskoning Nederland B.V. for Tata Steel IJmuiden B.V.
**Year:** 2025, definitive version 15 September 2025
**URL:** https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf
**Relevant locators:** §5.2.2 EAF-installatie; §11.1 Elektrische vlamboogoven (EAF); §11.2 Secundaire metallurgie; §11.3 Afgasbehandeling; §11.5 Energievoorziening.
**Exact values used:** 2.8 Mt/y hot DRI; about 1 Mt/y scrap; about 3.3 Mt/y liquid steel; EAF batch process; three described process steps; arc power stepped during cycle; electrodes withdrawn before tapping; hot heel retained; approximately 325 t liquid steel per tap; Consteel/scrap preheating; oxyfuel burner with natural gas.
**Caveat:** Public technical description, not a full operational heat schedule or bidding model.

### S2 — MER Heracless Energy and CO2 detail study

**Title:** *MER Heracless - Detailstudie Energie en CO2-balans*
**Organisation / client:** Royal HaskoningDHV / Tata Steel IJmuiden B.V.
**Year:** 2025, definitive version 15 September 2025
**URL:** https://pas.commissiemer.nl/files/nl/3730/01-Energie.pdf
**Relevant locators:** §5.3 Nieuwe installaties: EAF; §5.3.1.4 Warmteterugwinning uit afgassen; §5.3.2 Energiebalans vlamboogoven; Table 5.1; Table 5.2; §5.4 Secondary metallurgy.
**Exact values used:** scrap preheat 300-350 °C; off-gas after horizontal feed system 1100 °C average / 1300 °C peak; off-gas cooled to 580 °C average / 750 °C peak before iRecovery; off-gas/economizer steam at 16 bar(g), 204 °C; steam production 38 t/h in NG scenario and 32 t/h in H2-rich scenario; EAF energy balance: HDRI 1.28 GJ/t LS, scrap heat 0.14 GJ/t, electricity 1.52 GJ/t, coke breeze/anthracite 0.27 GJ/t, electrodes 0.03 GJ/t, NG 0.05 GJ/t, total 3.30 GJ/t; energy-balance production basis 458 t LS/h; off-gas steam recovery 76 kWh/t; secondary-metallurgy electricity 31 kWh/t average and 23-42 kWh/t range; RH degasser steam 17 t/h per degasser.
**Caveat:** Design/vendor-based energy balance. Use as public candidate values, not confidential operating truth.

### S3 — JRC BREF for EAF generic ranges

**Title:** *Best Available Techniques (BAT) Reference Document for Iron and Steel Production*
**Authors:** Remus, R.; Aguado-Monsonet, M. A.; Roudier, S.; Delgado Sancho, L.
**Organisation:** European Commission Joint Research Centre
**Year:** 2013
**URL:** https://bureau-industrial-transformation.jrc.ec.europa.eu/sites/default/files/2019-11/IS_Adopted_03_2012.pdf
**Relevant locator:** Chapter 8, Table 8.1 Electric arc furnace input/output ranges.
**Exact values used:** electricity 404-748 kWh/t LS; oxygen 5-65 Nm3/t LS; fuels 50-1500 MJ/t LS; coal 3-28 kg/t LS; electrodes 2-6 kg/t LS; lime/dolomite 25-140 kg/t LS; CO2 72-180 kg/t LS; slag 60-270 kg/t LS; off-gas 8000-10000 Nm3/t LS.
**Caveat:** Generic EU EAF range, mostly scrap-EAF oriented. Do not override Tata-specific Heracless energy-balance values without justification.

### S4 — Boldrini et al. EAF flexibility review

**Title:** *Flexibility options in a decarbonising iron and steel industry*
**Authors:** Boldrini, A.; Koolen, D.; Crijns-Graus, W. H. J.; van den Broek, M.
**Journal:** Renewable and Sustainable Energy Reviews 189, 113988
**Year:** 2024
**DOI:** https://doi.org/10.1016/j.rser.2023.113988
**URL:** https://www.sciencedirect.com/science/article/pii/S1364032123008468
**Relevant use:** EAF batch processes as flexibility source; interruption caution; review states that according to Paulus et al. an EAF melting interruption longer than 30 minutes forces process restart.
**Caveat:** Generic literature review. Use as a conservative flexibility guardrail, not a Tata-specific control rule.

### S5 — Paulus and Borggrefe DSM source

**Title:** *The potential of demand-side management in energy-intensive industries for electricity markets in Germany*
**Authors:** Paulus, M.; Borggrefe, F.
**Journal:** Applied Energy, 88(2), 432-441
**Year:** 2011
**DOI:** https://doi.org/10.1016/j.apenergy.2010.03.017
**Relevant use:** Original DSM literature source cited by Boldrini et al. for EAF interruption behaviour.
**Caveat:** Germany-wide industrial DSM source; review original before making thesis-grade EAF interruption claims.

### S6 — Athanasiadis modelling precedent

**Title:** *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel's IJmuiden Site*
**Author:** Athanasiadis, I.
**Institution:** Delft University of Technology
**Year:** 2025
**Relevant locators:** EAF modelling approach; PyPSA Link structure; EAF as batch process; committable/on-off unit; parameter confidentiality caveat.
**Use:** Supports using a binary/committable EAF representation rather than a smooth continuous dimmer.
**Caveat:** Public thesis precedent only; not exact Tata parameter truth.

### S7 — Badarinath modelling precedent

**Title:** *Optimising Industrial Participation in the Day-Ahead Electricity Market: A Stochastic Bidding Framework with Risk Management*
**Author:** Badarinath, M.
**Institution:** Delft University of Technology
**Year:** 2025
**Relevant locators:** semi-continuous EAF formulation, DRI-buffer decoupling, EAF maintenance/off constraints, DRP-EAF price responsiveness.
**Use:** Supports semi-continuous formulation and the need to avoid treating the EAF as a free dimmer.
**Caveat:** Secondary precedent; not source evidence for physical heat-cycle details.
