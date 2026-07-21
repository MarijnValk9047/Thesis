# C5 WAG Reconciliation Repair Plan

## Purpose

This note turns the July 2026 C1 WAG, electricity and emissions diagnostic into a small number of source-backed repairs.  It is the successor to the diagnostic contract: it does not tune gas yields to annual anchors, create a Wobbe model, invent WAG/NG shares, or activate economics.

The active carrier policy remains:

- BFG, COG and BOFG are separate LHV-energy carriers.
- `mixed_wag` and `aggregate_wag` are never physical model inputs.
- Named NG may meet a named, eligible controller demand only after eligible WAG is exhausted.  Site NG residual remains reporting only.
- WAG-explicit combustion CO2 is separate from aggregate process-counter CO2.

## What the current C1 diagnostic actually says

The exact 6.75-Mt/y C1 diagnostic, run with the source-envelope metallics
case, annualises to **19.695329 PJ_LHV/y** gross BFG, COG and BOFG generation:
BFG 11.253668 PJ/y, COG 6.610912 PJ/y and BOFG 1.830749 PJ/y.  Its 168-hour
physical solve is optimal in about 15 seconds and every carrier balance closes.
It is not directly comparable with the older C5p_m 13.885 PJ/y activity-only
diagnostic: the source activities, utility boundary and WAG sinks differ.
Neither result may be used as the other result's validation anchor.

The current run writes `wag_sink_mix_ledger.csv`, so that each realised flow
remains explicit.  For the C1 target case the HSM controller uses COG first,
then BFG, then BOFG and finally named NG only if needed.  Its realised annual
HSM mix is 0.889055 TWh_LHV COG, 1.276570 TWh_LHV BFG, 0 BOFG and 0 NG.  This
is a carrier precedence rule, not a fixed blend.

The active result is also not directly comparable with Athanasiadis Table 9's
`Total WAGs Generation = 1.23 TWh`.  Table 9 does not define whether that
field is gross gas energy, net surplus gas, generator fuel, or generator
electricity.  It remains model-precedent context only and may not drive a gas
yield correction.

The comparable C1 MER generator quantities are more precise:

| Metric | Source-backed C1 value | Correct treatment |
|---|---:|---|
| WAG to VN25/IJ01 | 10.5 PJ/y | Carrier-specific validation subtotal: BFG 9.1, BOFG 1.3, COG 0.1. |
| Named NG to VN25 | 4.1 PJ/y | Separate named-generator-NG context; not WAG and not a residual plug. |
| Generator total fuel plus flare | 14.6 PJ/y | Context total only; never compare directly with a WAG-only model subtotal. |
| C1 flare | 0.1 PJ/y | Separate flare validation row; carrier split still unavailable. |

The present exact-target WAG-to-generator result is 2.434519 PJ/y.  It is
below the comparable 10.5-PJ/y WAG subtotal, but the gap is not filled: the
model has a partial electricity boundary and an internal no-export rule, while
the published annual generator rows are validation context rather than an
hourly schedule.  The mismatch is therefore reported, not calibrated with
unallocated NG or an electricity residual.

## Findings that need repair

| ID | Finding | Evidence | Why it matters | Repair |
|---|---|---|---|---|
| WAG-R1 | The active selected LHV map is BFG 3.35, COG 18.7 and BOFG 9.58 MJ/Nm3. | `s3_wag_selected_dev_inputs.csv` and the active `wag_milp_input_contract`. | Later source cards contain alternate candidate values. | **Closed for this diagnostic layer:** all model and reporting conversions read the same governed S3 selection. Alternatives remain explicit sensitivity candidates; gas volumes are not changed to compensate. |
| WAG-R2 | The C1 material chain converts `t dry coal` to `t coke` with the source-backed 1.285 factor. | `process_io_coefficients.csv`; `Coking_Plants_Parameters.md`. | KGF self-use must use the same coke basis as the underfiring intensity. | **Implemented:** `COG_to_KGF_underfiring` uses the C1 coke-output expression, while COG generation remains on dry-coal activity. |
| WAG-R3 | HSM used an old BFG-first deterministic tie-breaker. | Unified builder objective and HSM source-card eligibility. | BFG-first is not a Tata source fact. | **Implemented as an explicit development case:** `COG -> BFG -> BOFG -> NG`, after mandatory carrier-specific sinks.  It creates no fixed mix and writes the realised carrier flows. |
| WAG-R4 | The generator interface cap is compiled from a prior C5p_c allocation with WAG gaps, not directly from the newer active-throughput WAG surface. | C5p_c generator ledger and current central run. | A previous residual allocation is acting as a limit in a different physical run. | Separate generator nameplate/operation envelope from annual fuel anchors. Use the MER carrier rows as validation only; report an unserved anchor gap, rather than using the old allocation as a physical cap. |
| WAG-R5 | C1 flare is zero in the current integrated run but 0.1 PJ/y in the source context; the current stage cannot split that flare by carrier. | Current C1 run; MER Table 5.5 context in generator card. | Zero flare is not proof that the route is fully represented. | Add a single reported, unsplit-flare gap row. Do not assign it to BFG, COG or BOFG and do not add flare CO2 until a carrier split exists. |
| WAG-R6 | The 3.418 Mt/y Mode-B WAG combustion subtotal is compared with a full-site 8.3-Mt/y Scope-1 anchor. | Exact 6.75-Mt/y C1 utility ledger. | These have different boundaries. The difference is missing boundary coverage, not evidence that a WAG CO2 factor is wrong. | Keep Mode B as a represented-sink subtotal and report the 4.882-Mt/y site Scope-1 residual separately. Never fill it with aggregate BF/BOF/KGF/sinter counters. |

## Source-backed target architecture

The tractable layer is a carrier-specific energy ledger, not a gas-quality simulator:

```text
production-coupled BFG / COG / BOFG
        |
        +--> mandatory self-use
        |     - BF hot stove: BFG base, 2.20 GJ/t hot metal
        |     - KGF underfiring: COG only
        |     - Sinter: COG where the existing controller is active
        |     - PEFA: BOFG/NG for Malerij; COG/NG for Branderij; no BFG
        |
        +--> HSM reheat controller
        |     - COG then BFG then BOFG, then named NG backup
        |     - realised carrier mix is reported; no ratio is imposed
        |
        +--> boilers and steam
        |     - existing carrier eligibility remains unchanged
        |
        +--> VN25 / IJ01 interface
        |     - BFG, BOFG, COG; named VN25 NG reported separately
        |
        +--> carrier-specific flare / residual reporting
```

This tracks every plant's realised mix in `MWh_LHV` by carrier without requiring a Wobbe index, gas-holder simulation, or fixed WAG/NG percentage.

## Correct coking basis

The Coking Plants card gives a central dry-coal requirement of 1.285 t dry coal/t coke, a COG yield of 8.1 GJ/t coke and KGF underfiring of 3.55 GJ/t coke.  Therefore the consistent conversion is:

```text
coke_output_t = dry_coal_input_t / 1.285
gross_COG_GJ = coke_output_t * 8.1
KGF_underfiring_GJ = coke_output_t * 3.55
COG_surplus_GJ = gross_COG_GJ - KGF_underfiring_GJ
```

Equivalently, on the current model's dry-coal activity basis, KGF underfiring is `3.55 / 1.285 = 2.763 GJ/t dry coal`.  The existing 1.0 coke-per-dry-coal proxy and its direct use of a per-coke underfiring intensity must not remain in an anchor-reconciliation run.

This repair can expose a real coking-capacity or coke-demand feasibility issue.  That is an intended result: capacity must be checked against the source-backed KGF1 annual production context, rather than avoided by retaining a unit-inconsistent WAG self-use expression.

## Active LHV decision and later review boundary

The source cards currently define the later canonical development set as BFG 3.85, COG 18.5 and BOFG 8.6 MJ/Nm3.  Applying those values to the current C1 volumes would change gross WAG energy from 26.291 to approximately 28.18 PJ/y: BFG increases from 15.023 to 17.268 PJ/y, COG reduces from 8.825 to 8.731 PJ/y, and BOFG reduces from 2.444 to 2.194 PJ/y.

This would be an internal-unit correction, not an anchor-fit adjustment.  It
does not solve the Athanasiadis Table 9 comparison and would have to be carried
through every WAG sink and CO2 calculation in the same run.  For the current
diagnostic layer, the governed S3 selection remains the sole active map; later
source-card values are transparent sensitivity candidates, not implicit
overrides.

## Ordered implementation gates

1. **Coking-basis repair and material feasibility check — implemented.** The
   dry-coal/coke conversion and KGF self-use now use compatible bases.
2. **Single LHV registry migration — implemented for the active selection.**
   Every active conversion reads the same governed S3 map. A later alternative
   factor review remains a sensitivity task, not a blocker for this layer.
3. **HSM-controller case split — implemented.** The explicit COG/BFG/BOFG/NG
   precedence creates a reported carrier mix without a fixed ratio.
4. **Generator-interface hardening — still diagnostic-only.** The annual
   source rows remain validation anchors; the current fixed interface cap must
   not be presented as a source-proven unit nameplate or as an anchor target.
5. **Annual WAG and Mode-B CO2 reconciliation — implemented as reporting.**
   Gross, sink use, generator fuel, flare, electricity offset and point-of-
   oxidation CO2 are separate; only comparable rows may be scored later.

Each gate must pass carrier balances, keep residuals visible, preserve production/material feasibility, and create no aggregate-WAG physical route or aggregate-process-plus-Mode-B CO2 total.

## Gate 1 execution — C1 coking self-use basis

The material chain was already source-corrected: its C1 `coke_output` expression is dry-coal input divided by 1.285.  Gate 1 corrects the remaining WAG sink only: `COG_to_KGF_underfiring` now uses that coke-output expression.  It does not alter COG generation, gas LHV, carrier eligibility, WAG priority, NG backup, or residual reporting.

On the 168-hour central C1 capacity/utility diagnostic, this preserves the annualised final-product capacity at 6.705782 Mt/y and the gross COG generation at 2.451373 TWh_LHV/y.  The COG process/self-use subtotal falls from 1.294022 to 1.015227 TWh_LHV/y.  The freed carrier remains carrier-specific and is allocated only by the existing controller/tie-breaker layer; the run reports its generator, boiler and carrier-specific flare destinations separately.  This is a coking-basis repair, not an annual-anchor calibration.

The generic rolling wrapper initially stopped in its C0 reporting layer because C0 has no executable oxygen-demand variable.  That layer now reports zero represented oxygen rather than constructing an implicit oxygen residual.  It does not add C0 oxygen demand or change C0 process physics.

## What this will and will not solve

The repairs will produce a defensible WAG layer: the numerical gas energy, self-use, sink allocation, generator comparison and CO2 subtotal will use compatible bases.  They may show that the C1 route has a genuine KGF/coke or generator-envelope shortfall; that is useful physical information.

They will not make a whole-site Scope-1 claim, infer missing site NG, force the Athanasiadis total-WAG field to match, or recreate real-time Wobbe mixing.  Those outcomes would require additional source evidence and are deliberately outside this thesis abstraction.

## Source-context reconciliation execution (C1, 6.75 Mt/y)

The former low generator-WAG result was not a suitable central source-context
comparison.  The free-route exact-target run selected about 37.8% BOF liquid
steel, whereas the already registered `central_source_ratio` scenario fixes the
BOF share at `3.4 / 6.75 = 50.3703704%`.  Because BFG is production-coupled to
the retained BF--BOF route, the free route structurally reduced BFG before any
WAG-controller conclusion could be drawn.

The diagnostic case
`steel_c1_6_75_wag_sink_source_reconciliation.yaml` therefore combines only
three explicitly labelled sensitivity policies:

1. the existing central-source-ratio route scenario;
2. the Athanasiadis HSM controller architecture (`COG`, then named `NG`
   backup) plus its separately reported 45-MW Linde/N2 context load, used as
   model-precedent sensitivity rather than Tata truth; and
3. `volume_envelope_only` at the generator interface.  This removes the old
   allocation-derived C5p_c profile ceiling, while retaining the existing
   structural gas-volume envelope.  It is not a nameplate-capacity increase.

The 168-hour run is optimal, preserves the 6.75-Mt/y target and closes every
carrier balance.  Its WAG generator subtotal is **9.860754 PJ/y**, compared
with the carrier-specific MER context total of **10.5 PJ/y**:

| Carrier | Model generator fuel (PJ/y) | MER context (PJ/y) | Difference |
|---|---:|---:|---:|
| BFG | 8.333659 | 9.1 | -8.4% |
| COG | 0.000000 | 0.1 | -0.1 PJ/y |
| BOFG | 1.527095 | 1.3 | +17.5% |
| **Total WAG** | **9.860754** | **10.5** | **-6.1%** |

This is a meaningful closure of the previously 2.434519-PJ/y generator-WAG
subtotal.  It is not a calibration: no gas yield, LHV, WAG/NG share or annual
anchor was imposed as a constraint.  Named HSM backup NG is visible at
3.300623 PJ_LHV/y; it is not an unallocated site-NG plug.

The realised 312.682-MWh_LHV/h generator fuel flow is above the old
181.907-MWh_LHV/h profile-derived cap.  The audit therefore records that cap
as **not active** in this source-envelope sensitivity; it must not be called
non-binding.  Any migration of the volume envelope to a base case requires a
separate source/nameplate review.

Remaining gaps are intentionally not "repaired" by this run:

- gross electricity is 3.584155 TWh/y, still a partial represented boundary;
- WAG-explicit combustion CO2 is 4.561450 MtCO2/y, a represented Mode-B
  subtotal rather than the 8.3-Mt/y site Scope-1 anchor;
- Athanasiadis Table 9 total WAG remains not comparable because its exact
  energy/electricity boundary and denominator are unresolved.

## Full-plant electricity sensitivity follow-up

The source-context WAG result was then held fixed while two separately
traceable, throughput-linked electricity sensitivities were run.  This is
important: neither sensitivity creates an electricity residual or changes a
WAG allocation.

| C1 6.75-Mt/y diagnostic | Gross electricity (TWh/y) | Gap to 4.944-TWh official context | Badarinath visual IQR rows (of 27) |
|---|---:|---:|---:|
| WAG source context plus Linde/N2 | 3.584155 | -27.5% | 7 |
| + EAF secondary metallurgy, 0.031 MWh/t LS | 3.688005 | -25.4% | 9 |
| + DSP high sensitivity, 0.104 MWh/t coil | 3.760005 | -24.0% | 12 |

The EAF addition is an explicit 31-kWh/t secondary-metallurgy row from the
EAF source-card/MER context.  The DSP high value is a generic HSM proxy and
therefore sensitivity-only.  Both preserve final-product output at 6.75 Mt/y,
all WAG balances, the 9.860754-PJ/y WAG-generator subtotal and the Mode-B
CO2 subtotal.  They improve the electricity representation, but do not close
the remaining site-boundary gap and must not be promoted silently to base
inputs.

### Why the remaining generator-carrier split is not tuned further

The final source-context carrier ledger makes the obstruction explicit:

- BFG generation is 15.016576 PJ/y.  BF hot-stove use plus boiler use is
  6.682917 PJ/y, leaving 8.333659 PJ/y for generators.  Reaching the 9.1-PJ/y
  validation row would require a change to BFG generation, BF output or a
  mandatory sink—not an allocation tie-breaker.
- COG generation is 8.821414 PJ/y.  Mandatory coking/sinter use is
  3.653356 PJ/y and HSM/PEFA uses the entire remaining 5.168058 PJ/y.  A
  0.1-PJ/y COG generator flow would therefore displace COG from the HSM and
  add named NG, unless a new source-backed sink-demand or gas-generation rule
  is introduced.
- BOFG generation is 2.442900 PJ/y.  PEFA uses 0.915805 PJ/y and the remaining
  1.527095 PJ/y goes to the generator.  Reducing it to the 1.3-PJ/y validation
  row requires a new eligible BOFG sink or an explicit carrier-split flare;
  neither is currently source-backed.

The 0.1-PJ/y COG, 0.77-PJ/y BFG and 0.23-PJ/y BOFG differences are therefore
kept as carrier-specific validation residuals.  Imposing those values as
minimum or maximum flow constraints would be anchor calibration and is not an
acceptable physical repair.
