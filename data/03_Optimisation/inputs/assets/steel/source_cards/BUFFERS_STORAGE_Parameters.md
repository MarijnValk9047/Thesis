# Buffers And Storage Parameters - C0/C1 Central Register Source Card

## 1. Status and workflow

This note is a **central buffer/store register and source-card synthesis** for the public Tata Steel IJmuiden-inspired C0/C1 steel process model.

It is **not** an executable input table and not thesis-approved truth. It harmonises buffer and storage assumptions that are currently spread across plant-specific source cards and C5 development stages.

Normal workflow still applies:

```text
source -> plant/source-card evidence -> candidate evidence -> assumption/register row
       -> reviewed development input -> executable model input -> later thesis approval gate
```

This register should be used to:

- identify which buffers/stores are already active in the current C5 model;
- distinguish physical stores from accounting accumulators and exogenous supplies;
- prevent fake flexibility from unconstrained storage;
- make terminal rules, capacity assumptions and caveats explicit;
- provide a single reference for future buffer/store validation diagnostics.

It should **not** be used to silently replace current C5 baseline values.

---

## 2. Scope and abstraction level

### Configurations

- `C0_current_BF_BOF_reference`: current BF-BOF reference.
- `C1_phase1_BF_BOF_plus_DRP_EAF`: Phase 1 hybrid BF-BOF + NG-DRP + EAF.

## 3. Buffer/store category vocabulary

| Category | Meaning | May create operational flexibility? | Base treatment |
|---|---|---:|---|
| `active_physical_store` | Physical intertemporal buffer with capacity, initial inventory and terminal rule. | Yes | Allowed only when capacity and terminal policy are explicit. |
| `active_practically_nonbinding_bulk_solid_store` | Bulk-solid stockpile with very high/non-binding capacity, but no free material source. | Limited | Allowed for coke, sinter and pellets if terminal/no-free-source diagnostics pass. |
| `active_interface_or_accounting_buffer` | Interface/balance item used to connect plants, not a dispatchable physical store. | No or limited | Allowed if not used as hidden slack. |
| `structural_or_validation_anchor_only` | Physical structure exists, but model-ready capacity is not public or not governed. | No | Report only. Do not dispatch. |
| `deferred_or_sensitivity_only` | Candidate value exists but is not active in the baseline. | Not in base | Sensitivity only after explicit approval. |
| `blocked_as_store` | Must not be modelled as store in current baseline. | No | Use bus/balance/spill/diagnostic instead. |

---

## 4. Current C5 baseline interpretation

The current C5 baseline already contains several buffer/store treatments. This register must therefore **audit and align** the model rather than re-implement all buffers from scratch.

| Buffer/store family | Current C5 baseline interpretation | Action in this register |
|---|---|---|
| Coke, sinter and fired pellets | Practically non-binding bulk-solid stores with no-free-source and terminal/inventory diagnostics. | Keep active policy. Do not replace with artificial tight caps. |
| DRI buffer | Active finite C1 buffer between continuous DRP and EAF handoff. Current C5 value is approximately 15.230 kt under active 6.75 Mt/y scaling. | Keep current active value; record other values as candidate/sensitivity. |
| Slab/hot-cold scaffold | Active through HSM/WBW C5l_d base_0_50 and related downstream routing. | Keep current C5l_d baseline; do not overwrite with a new slab capacity unless explicitly reviewed. |
| Oxygen buffer | C5p_a treats oxygen buffer as balancing/structural only; 1670 m3 geometric vessel volume is not converted to usable Nm3/t without pressure. | Keep structural-only base; 100 t candidate is sensitivity only. |
| Steam | Steam is a bus/utility balance, not a store. | Keep blocked as store. |
| WAG holders | BFG/COG/BOFG holders are topology/context; not active hourly stores. | Keep blocked as store; use carrier balances, sinks, spill/flare. |
| Hot metal | Current C5k/C5m baseline uses no BF-to-BOF hot-metal buffer: BF hot metal equals BOF hot-metal input when no buffer is active. | Do not activate hot-metal store in base; keep candidate/sensitivity only. |
| Liquid steel | Ladle/tundish timing only; not a free intertemporal store. | Block as store. |
| Finished product | Fulfilment/accounting denominator only. | Do not treat as flexibility store. |
| Internal scrap/loss | Reporting-only unless governed scrap-pool layer is opened. | Keep reporting-only. |

---

## 5. DSP/HSM and downstream route anchors

| Configuration | Raw public anchor | Current C5 interpretation | Register treatment |
|---|---:|---|---|
| C0 DSP output | 1.5 Mt/y DSP rolls | C5 active DSP output currently follows active 6.75 Mt/y route scaling, around 1.35 Mt/y. | Raw anchor = validation; active C5 value = development target. Report gap. |
| C0 HSM/WBW output | 5.4 Mt/y rolled coils | Current C5 final-product proxy is lower than raw MER final-product anchor. | Validation gap; denominator remains unresolved. |
| C1 DSP output | max. 1.5 Mt/y DSP rolls | C5 active DSP output currently around 1.35 Mt/y. | Raw anchor = validation; active C5 value = development target. |
| C1 HSM/WBW output | max. 5.5 Mt/y rolled coils | C5 HSM/WBW follows C5l_d base_0_50 and imported slab treatment. | Keep current C5l_d baseline; report raw-anchor gap. |
| C1 imported slab | 0.6 Mt/y context/anchor | Exogenous supply / validation anchor, not storage capacity. | Keep separate from slab inventory. |

**Rule:** raw public annual values are validation anchors unless explicitly promoted into development input rows. They must not become hidden hourly dispatch constraints.

---

## 6. Central buffer/store register

| Buffer ID | Carrier/state | C0 | C1 | Current C5 status | Active base value / policy | Candidate or source-context value | Initial / terminal rule | Flexibility risk | Stage/reference | Decision |
|---|---|---:|---:|---|---|---|---|---|---|---|
| `iron_ore_stockpile` | iron ore / raw-material stockpile | yes | yes | structural_or_validation_anchor_only | No finite cap in first MILP. | Public raw-material stockpile topology. | n/a | Low if exogenous; high if used as free source. | PEFA / sinter / raw material context | Keep exogenous/context; not a flexibility store. |
| `coal_blend_stockpile` | coal blend | yes | reduced | structural_or_validation_anchor_only | No finite cap in first MILP. | Public coal blending topology. | n/a | Low if exogenous; high if used as free source. | KGF/coking context | Keep exogenous/context; not a flexibility store. |
| `coke_store` | solid coke | yes | yes, KGF1/BF6 route | active_practically_nonbinding_bulk_solid_store | Practically non-binding bulk-solid policy; no-free-source diagnostics. | Candidate tight caps deferred. | Terminal/inventory diagnostics if represented. | Can hide coke imbalance if external fallback active. | C5n_b/C5m_f | Keep active baseline; external coke fallback only. |
| `sinter_store` | sinter | yes | yes, BF6 route | active_practically_nonbinding_bulk_solid_store | Practically non-binding bulk-solid policy. | Candidate tight caps deferred. | Terminal/inventory diagnostics if represented. | Can decouple sinter/BF too much if production becomes flexible. | C5n_b / sinter layer | Keep active baseline. |
| `fired_pellets_proxy_store` | fired pellets | yes | yes | active_practically_nonbinding_bulk_solid_store | Practically non-binding bulk-solid policy; PEFA + imports supply BF/DRP demand. | Imported pellets anchors remain validation/supply rows. | Terminal/inventory diagnostics; no hidden imports. | Can hide BF/DRP burden gaps if import/slack hidden. | C5n_a/C5n_b | Keep active baseline. |
| `hot_metal_store` | liquid hot metal / torpedo interface | no active base | no active base | deferred_or_sensitivity_only | Current C5 no-buffer baseline: BF hot metal equals BOF hot-metal input. | Athanasiadis-style candidate: 500 t, initial 250 t, terminal equality. | If activated: finite cap, initial 50%, end=start. | High: changes BF-BOF rigidity and coke reconciliation. | BF/BOF/C5k/C5m_f | Do not activate in base. Sensitivity only. |
| `liquid_steel_ladle_buffer` | liquid steel before caster/DSP | no | no | blocked_as_store | Timing/interface only. No multi-hour store. | Ladle/tundish process buffer context. | n/a | Very high if used as free storage. | BOF/EAF/DSP/HSM | Block as intertemporal store. |
| `slab_yard_total_store` | steel slabs, total yard | yes | yes | active_interface_or_accounting_buffer | Use current C5l_d resolved slab/hot-cold scaffold. Do not overwrite. | Athanasiadis precedent candidate: 25,000 t; sensitivity 10k/25k/50k. | Total terminal neutrality according to current C5l_d policy. | High: slab yard can become free energy/production battery. | C5l_d HSM/WBW | Audit current value; keep baseline. |
| `hot_slab_age_buckets` | hot slabs / age buckets | yes | yes | active_interface_or_accounting_buffer | Use current C5l_d base_0_50 hot-charge/capped hot-share policy. | Hot-to-cold candidate: 2/6/12 h sensitivity. | Hot inventory should not be mined at horizon end; hot end ideally zero unless current policy says otherwise. | High: free hot slabs avoid reheating. | C5l_d | Audit; no base change. |
| `cold_slab_store` | cold slabs | yes | yes | active_interface_or_accounting_buffer | Use current C5l_d policy. | Candidate values depend on slab-yard assumption. | Terminal neutrality as current policy. | Medium: can shift HSM load if unconstrained. | C5l_d | Audit; no base change. |
| `external_slab_import` | exogenous slab supply | small/context | yes | blocked_as_store | Exogenous supply/validation anchor only. | C0 around 16 kt/y context; C1 0.6 Mt/y MER context if final-product anchors followed. | n/a | High if treated as unlimited store. | HSM/WBW/DSP | Keep supply row, not store. |
| `reheat_state_energy` | energy consequence of slab state | yes | yes | structural_or_validation_anchor_only | Not a storage capacity. Governed by HSM/WBW heat policy. | Direct-hot 0.335, hot 0.878, cold 1.338 GJ/t are generic candidates. | n/a | Can distort energy if used outside HSM heat policy. | HSM/WBW C5l_d | Reference only; no direct store input. |
| `caster_aux_energy` | throughput-coupled auxiliary energy | yes | yes | structural_or_validation_anchor_only | Not a store. | 0.06 GJ/t generic benchmark candidate. | n/a | Low; but boundary/denominator issue. | downstream/HSM | Keep deferred or linked only. |
| `oxygen_short_buffer` | gaseous oxygen buffer | structural | structural | structural_or_validation_anchor_only | C5p_a: balancing_buffer_only; no usable capacity from vessel volume. | 1670 m3 geometric vessel anchor; 100 t Athanasiadis candidate sensitivity only. | If activated later: finite cap, start=end, no DA arbitrage. | High: oxygen can become price battery. | C5p_a Linde/ASU | Keep structural-only base. |
| `dri_buffer` | CDRI/DRI buffer | no | yes | active_physical_store | Current C5: approx. 15.230 kt under active 6.75 Mt/y scaling; 50% initial; end=start. | 2 days DRP output; candidate/predecessor values around 15.35–17.76 kt depending basis; sensitivity 1–3 days. | initial 50%; terminal equality. | Very high: main C1 flexibility source. | C5o_a/C5o_b | Keep active C5 value; sensitivity later. |
| `hdri_transfer` | hot DRI transfer | no | yes | active_interface_or_accounting_buffer | Short transfer/interface only. No long-duration store. | HDRI direct-to-EAF topology. | End zero if represented. | High if treated as store. | DRP/EAF | Keep as interface, not store. |
| `scrap_supply_or_scrap_yard` | scrap supply / scrap park | yes | yes | structural_or_validation_anchor_only | Annual supply/demand/reporting. No dynamic store unless capacity governed. | C0/C1 scrap anchors from route source cards; internal scrap reporting-only. | n/a | High if internal scrap becomes free EAF input. | EAF/DSP/HSM/BOF | Keep reporting/supply; no dynamic store. |
| `internal_scrap_loss_stream` | internal scrap from rolling/DSP losses | yes | yes | structural_or_validation_anchor_only | Reporting-only unless governed scrap-pool layer is opened. | DSP internal scrap/loss currently reporting-only. | n/a | High if becomes free EAF input. | C5o_c | Keep reporting-only. |
| `bofg_holder` | BOFG/oxygas holder | yes | yes | blocked_as_store | Do not model as hourly store in current baseline. | Physical holder/topology context. | n/a | High: WAG storage arbitrage. | WAG/generator/BOF | Block as dispatch store. |
| `bfg_cog_holders` | BFG/COG holders | yes | reduced | blocked_as_store | Do not model as hourly store in current baseline. | Gas-holder topology context. | n/a | High: WAG storage arbitrage and Wobbe issues. | WAG network | Block as dispatch store. |
| `steam_store` | steam accumulator/storage | no active base | no active base | blocked_as_store | Steam is bus/utility balance, not store. | No source-backed storage capacity. | n/a | Very high: steam battery. | C5p_b boiler/steam | Block as store. |
| `finished_product_accounting` | final-product fulfilment / inventory accounting | yes | yes | active_interface_or_accounting_buffer | Fulfilment/denominator accounting only. | C0/C1 final-product anchors. | Final target/fulfilment; not flexibility store. | Can hide denominator inconsistency if misused. | DSP/HSM diagnostics | Keep accounting-only. |
| `generator_fuel_interface` | residual WAG to generators | yes | yes | active_interface_or_accounting_buffer | Generator fuel interface, not WAG storage. | C0 residual-WAG-derived electricity offset; C1 annual generator anchors. | n/a | High if WAG is stored/valued directly. | C5p_c | Keep interface; no storage. |

---

## 7. Active baseline decisions

The following decisions should be treated as the current development baseline unless explicitly reopened:

1. **Bulk solids are practically non-binding, not free sources.** Coke, sinter and fired pellets may have non-binding bulk-solid storage policy, but imports/fallbacks must be explicit.
2. **No hot-metal buffer in base.** The current C5 BF-to-BOF link remains no-buffer unless a separate methodological change is approved.
3. **DRI buffer is active and finite in C1.** It is the main C1 route-decoupling buffer and must keep terminal equality.
4. **Slab/hot-cold logic follows current C5l_d.** Do not replace the active HSM/WBW slab scaffold from this register.
5. **Oxygen buffer is structural/balancing-only in base.** No 100 t active oxygen store unless pressure/usable-capacity assumptions are explicitly opened.
6. **WAG holders are not stores in C5.** WAGs remain carrier balances with explicit sinks, flare/spill/residual diagnostics.
7. **Steam is not a store.** Steam is represented by pressure-level buses and demand/supply balances.
8. **Internal scrap remains reporting-only.** It must not become free EAF scrap supply without a governed scrap-pool layer.
9. **Finished product is an accounting denominator, not flexibility storage.** Denominator remains unresolved until residual loads and boundary checks complete.

---

## 8. Sensitivities to preserve for later

| Parameter/topic | Low | Central/current | High | Status | Why |
|---|---:|---:|---:|---|---|
| DRI buffer days | 1 day | 2 days / current C5 approx. 15.230 kt | 3 days | sensitivity_required | Main C1 flexibility source; materially affects EAF shifting. |
| Slab total capacity | 10,000 t | current C5l_d value / 25,000 t candidate if aligned | 50,000 t | sensitivity_required | Downstream buffering can materially affect HSM and EAF route coupling. |
| Hot-to-cold threshold | 2 h | 6 h candidate / current C5 policy | 12 h | sensitivity_required | Affects reheating energy and hot-charge value. |
| Hot-metal buffer | 0 t active base | 500 t candidate | 1,000 t | deferred sensitivity | Would change C0 rigidity and BF/BOF coupling. |
| Oxygen usable capacity | structural only | 100 t candidate | 200 t candidate | deferred sensitivity | Requires pressure/usable volume assumption; can create DA arbitrage. |
| Initial slab inventory fraction | current C5 policy | 50% candidate | 100% | sensitivity_required | Endpoint and initial-state choices strongly affect flexibility. |
| Internal scrap recycling | reporting only | governed scrap-pool later | closed scrap loop | deferred | Avoid free EAF input. |

---

## 9. Required validation checks

A model-wide buffer/store diagnostic should report at least:

| Check | Required output |
|---|---|
| Presence/status matrix | active, diagnostic-only, structural-only, deferred, blocked. |
| Capacity table | current value, candidate value, unit, source role, active/deferred status. |
| Initial/terminal inventory | start, end, drift, terminal-rule pass/fail. |
| Min/max inventory | min, max, capacity hit count, negative inventory count. |
| Free-source check | imports/fallback/slack status for pellets, coke, scrap, slabs, DRI. |
| Free-battery check | whether store can create electricity/price response without physical basis. |
| Hot/cold slab check | hot end inventory, cold inventory, reheating consequence status. |
| DRI buffer check | capacity, start/end, EAF draw, DRP supply, drift. |
| Oxygen buffer check | structural only or active; if active, pressure/capacity caveat. |
| WAG/steam store check | WAG holders and steam store remain inactive. |
| Internal scrap check | reporting-only unless governed scrap-pool active. |
| Final-product check | accounting-only; not used as flexible inventory. |
| Anchor-gap check | raw anchors vs active scaled targets vs model outputs. |

Failure red flags should include:

```text
STORE_ACTIVE_WITHOUT_CAPACITY
STORE_ACTIVE_WITHOUT_TERMINAL_RULE
NEGATIVE_INVENTORY
TERMINAL_DRIFT_NONZERO
BULK_SOLID_STORAGE_USED_AS_FREE_SOURCE
HOT_METAL_STORE_ACTIVE_IN_BASE
OXYGEN_STORE_ACTIVE_WITHOUT_PRESSURE_OR_CAPACITY_ASSUMPTION
WAG_HOLDER_USED_AS_HOURLY_STORE
STEAM_STORE_ACTIVE
LIQUID_STEEL_STORE_ACTIVE
INTERNAL_SCRAP_USED_AS_FREE_EAF_INPUT
FINISHED_PRODUCT_USED_AS_FLEXIBILITY_STORE
HSM_BASE_0_50_REVERTED
DRI_BUFFER_CAPACITY_CHANGED_WITHOUT_METHOD_CHANGE
DENOMINATOR_SILENTLY_FROZEN
```

Caveats should include:

```text
DEVELOPMENT_ONLY_BUFFER_REGISTER
BULK_SOLID_CAPACITY_PRACTICALLY_NONBINDING
DRI_BUFFER_DEVELOPMENT_ASSUMPTION
SLAB_CAPACITY_OR_HOT_COLD_POLICY_DEVELOPMENT_ASSUMPTION
OXYGEN_BUFFER_STRUCTURAL_ONLY
WAG_HOLDERS_NOT_DISPATCH_STORES
STEAM_BUS_NOT_STORE
INTERNAL_SCRAP_REPORTING_ONLY
FINAL_PRODUCT_ACCOUNTING_ONLY
NOT_THESIS_APPROVED
```

---

## 10. Source-card cross-reference map

| Topic | Primary plant/source-card reference | Register role |
|---|---|---|
| Coke storage | KGF/coking and coke reconciliation records | Active bulk-solid policy and no external-coke fallback unless explicit. |
| Sinter storage | Sinter source-card / C5 sinter implementation | Active bulk-solid policy; BF-coupled production. |
| Pellet storage and imports | `PELLETIZING_Parameters.md` and pellet-burden layer | Active bulk-solid policy; PEFA + imports supply BF/DRP. |
| DRI buffer | `DRP_Parameters.md`, `EAF_Parameters.md`, Badarinath/Athanasiadis precedent | Active finite C1 buffer, terminal equality. |
| EAF/DRI handoff | `EAF_Parameters.md` | DRI draw from buffer; no hidden DRI/HBI. |
| DSP/HSM/slabs | `DSP_Parameters.md`, HSM/WBW C5l_d records | Downstream route accounting and slab/hot-cold scaffold. |
| Oxygen buffer | `LINDE_OXYGEN_Parameters.md` | Structural/balancing-only; no active t/Nm3 capacity in base. |
| Steam | `BOILER_STEAM_CIRCUIT_Parameters.md` | Steam buses, not store. |
| WAG/generator interface | `IJ01_VN25_GENERATORS_Parameters.md` | Fuel interface, not WAG storage. |
| Internal scrap | DSP/EAF/BOF/HSM records | Reporting-only until governed scrap pool. |
| Final-product denominator | C5 anchor/route/denominator diagnostics | Accounting only; denominator unresolved. |

---

## 11. Source notes

### Tata / MER Heracless

Royal HaskoningDHV. (2025). *MER Heracless – Groen Staal, Deel B: Technische beschrijving*. Tata Steel IJmuiden B.V., 15 September 2025.

Use in this register: C0/C1 production volumes, 20/80 DSP-WBW split, DSP/WBW final-product anchors, slab import context, DRI/EAF structure, HDRI/CDRI topology, scrap streams, oxygas/oxygen-buffer structure.

### Athanasiadis

Athanasiadis, I. (2025). *Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel’s IJmuiden Site*. MSc thesis, Delft University of Technology.

Use in this register: PyPSA Store precedent, candidate storage capacities and topology, gas/steam/generator component precedent. Public thesis values are modelling precedent, not public Tata-approved exact inputs.

### Badarinath

Badarinath, M. (2025). *Optimising Industrial Participation in the Day-Ahead Electricity Market: A Stochastic Bidding Framework with Risk Management*. MSc thesis, Delft University of Technology.

Use in this register: DRI buffer as key DRP-EAF decoupling mechanism, rolling-horizon inventory policy, EAF flexibility interpretation. Not a primary source for exact Tata storage capacities.

### Plant source-cards

This register must be read together with the current plant source-cards for PEFA, DRP, EAF, DSP, Linde/Oxygen, boiler/steam and IJ01/VN25 generator interface. Plant-specific source-cards remain the primary source of plant process parameters; this register harmonises only buffer/store status and validation logic.
