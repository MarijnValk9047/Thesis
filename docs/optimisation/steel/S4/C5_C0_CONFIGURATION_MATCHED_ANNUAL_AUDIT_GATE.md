# C5 C0 Configuration-Matched Annual Audit Gate

> **Historical diagnostic.** This report evaluates an inherited fixed C0
> schedule and cannot define the active C0 operating policy. The active model
> is quota-driven; use `C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md`
> for the current baseline and next gate. Fixed-schedule conclusions below are
> retained only as conditional lineage evidence.

## Decision

`GO_FOR_C0_DIAGNOSTIC_LINEAGE`; `NO_GO_FOR_C0_PHYSICAL_ACCEPTANCE_OR_ANNUAL_PROXIMITY_SCORING`.

The governed C0 fixed schedule has a current reproducible,
source-corrected schedule-basis diagnostic:
`steel_c0_source_corrected_schedule_basis_diagnostic_v5`. It has a resolved
configuration, solver diagnostics, a YAML-to-Pyomo fixed-schedule trace, an
explicit conditional cokes infeasibility proof, anchor rows and lineage
metadata. It is linked to the single canonical C1 physical baseline
`steel_c1_canonical_physical_baseline_v2`.

This closes the former schedule-trace gap and corrects the C0 coke unit basis.
It does not accept or score C0: the inherited profile has no source-backed
availability locator. Conditional on its 5/4/9-hour pattern, it can produce at
most 1,260.700 t coke/day while the active BF minimum requires at least
2,070.947 t/day, a 810.246 t/day deficit. This refutes the inherited profile,
not the physical C0 route. C0 must not be inferred from C1, scored from
historical static dispatch files or re-planned to conceal this result.

This is a comparability block only. It does not change C0 inputs, equations,
the governed fixed schedule, or any C1 module.

## Evidence inspected

| Surface | What it provides | Why it cannot score C0 now |
|---|---|---|
| `s4_4c5_full_scope_physical_diagnostics/s4_4c5_168h_hourly_dispatch_c0.csv` | 168-hour fixed-schedule C0 dispatch, carrier rows and internal electricity accounting | Historical static-regression artifact; no rolling quota/run manifest, current annual anchor contract, or configuration-matched guardrail bundle. |
| `s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation/` | Reconstructed C0/C1 annual development diagnostics | Compiles heterogeneous diagnostic stages rather than one current physical C0 solve; denominator, site electricity, NG and CO2 boundaries remain open. |
| `steel_c1_6_75_wag_generator_boundary_correction_v1` | Current exact-quota C1 run contract | C1 topology, downstream origin and utility boundary must not be projected onto C0. |
| `steel_c0_fixed_schedule_reporting_v1` | Historical pre-correction C0 fixed-schedule reporting diagnostic | Its dry-coal activity was placed on a coke inventory basis; retain for audit history only, never canonical C0 evidence. |
| `steel_c0_source_corrected_fixed_schedule_reporting_v1` | Earlier source-corrected execution before the schedule itself was traceable in YAML | Retain as diagnostic history only; the fixed-hour provenance was implicit and cannot support a C0 claim. |
| `steel_c0_source_corrected_schedule_basis_diagnostic_v4` | Historical C0 schedule-basis diagnostic before the C1 anchor classification was made strict | Retain for diagnostic lineage only. |
| `steel_c0_source_corrected_schedule_basis_diagnostic_v5` | Current C0 diagnostic with per-asset fixed hours, source status and Pyomo mapping in `c0_fixed_schedule_basis.csv` | No accepted solution under the inherited profile; it is explicitly not a source-backed availability calendar, so all C0 anchor rows remain blocked. |

## C0 anchor treatment until a matched run exists

| Anchor family | Current C0 numerator | Status | Reason / permitted use |
|---|---|---|---|
| Active final-product target (6.75 Mt/y) | Reconstructed final-product proxy | `reporting_only` | A target row is not proof that the historical C0 dispatch meets the current rolling quota contract. |
| MER/public liquid steel and final-product values | Historical/reconstructed C0 outputs | `not_comparable` | Production denominator and imported-slab/HSM/DSP origin treatment are not preserved in a current C0 run. |
| BFG/COG/BOFG generation and sinks | Historical carrier rows | `secondary_context_only` | May support a later C0 carrier audit, but no current C5p_o-backed rolling C0 ledger exists. |
| Gross electricity, grid import, generator offset | Historical process-scope accounting | `not_comparable` | Site/background load and internal-offset boundaries are incomplete. |
| Named NG and full-site NG | Explicit C0 NG is incomplete; full-site figure is residual context | `reporting_only` | Do not allocate residual NG or create plant WAG/NG ratios. |
| Mode-B explicit fuel CO2 and site Scope 1 | Partial represented fuel sinks | `not_comparable` | Mode-B subtotal cannot score against full-site Scope 1 or aggregate process counters. |

`<7.5%` is not applied to any row above because no C0 row currently passes
both numerator/denominator and run-lineage comparability checks. Negative
residuals remain visible in the historical diagnostics and must not be
floored.

## Required guardrails for the future C0 audit

A future C0 annual anchor audit may score only a run that provides all of the
following from the same configuration-matched physical execution:

1. governed fixed C0 schedule (no free C0 binary planning);
2. primary-source-backed C0 availability/calendar evidence for that fixed
   schedule, rather than a historical regression pattern;
3. source-traceable final-product denominator with explicit HSM and DSP
   origin routes before annualisation;
4. carrier-specific BFG/COG/BOFG ledger through process, steam/boiler,
   generator, flare and residual sinks, using C5p_o policy;
5. gross electricity, internal generation offset and net import as separate
   ledger fields; no residual electricity input;
6. named NG on a common LHV basis, separately from full-site residual NG;
7. Mode-B fuel CO2 separated from aggregate process counters and Scope-1
   context;
8. preserved final-product, HSM and DSP origin/denominator tags;
9. run manifest, resolved config, guardrail checks and source lineage.

The audit then classifies each anchor as `primary_score`,
`secondary_context`, `reporting_only`, `not_comparable` or `blocked`. A
`primary_score` row is within target only when its absolute signed residual
share is strictly below 7.5% and all physical guardrails pass.

## Next Safe Action

Use the completed C0 diagnostic only to repair a named structural blocker. The
next admissible repair is a source-backed fixed availability or schedule
calendar for KGF1/KGF2 and BF6/BF7 compatible with the sourced coke chain. It
must preserve governed fixed C0 binaries and must not change capacity, yields
or WAG factors for anchor fit. The C0 24-hour target is also a development
convention, not an annual Tata denominator; an executable HSM/DSP route must
close that denominator before a new annual C0 contract is accepted. The
remaining BF/sinter/burden and electricity-driver work stays explicit.
