# C5 Phase 5G Final Deterministic Freeze Gate

## Decision

`baseload_selection_gate_failed_model_not_frozen`

Phase 5G implemented the source-service overlap contract, constant electricity
and NG baseload interfaces, procurement and cost treatment, separate NG-CO2
proxy, and HERACLES validation additions. The explicit baseline and selected-
baseload validation each solved 56/56 rolling models. All 194 physical checks
and all eight HERACLES checks pass. The selected-baseload anchor gate fails for
C0 natural gas, so the attempted baseloads are not promoted, held-out evidence
is not admitted, the deterministic model is not frozen, and Phase 6 execution
is not authorised.

## Governed scope

- Run: `steel_c5_phase5g_final_deterministic_freeze_v1_20260728`.
- Output policy: `minimal`.
- Run class: `terminal_aware_deterministic_final_freeze_gate`.
- Lineage role: `canonical C5 final-freeze evidence`.
- Governed output contains 15 compact files (about 46 KB); rolling case caches
  remain disposable under `tmp/`.
- Phase 5E remains source-account reconciliation evidence. Phase 5D remains a
  historical sensitivity. Neither is active baseload logic.

## Source-service and selection result

The overlap contract applies

\[
U_{c,k,j}=\max(0,A_{c,k,j}-M^{validation}_{c,k,j})
\]

once per eligible source component. It excludes the incompatible 2.3/1.6-PJ/y
C0/C1 electricity boundary remainders. No model field maps to more than one
source component. The validation-weighted pools and attempted shared carrier
shares are:

| Carrier | Shared selected share | C0 pool (PJ/y) | C0 load (MWh/h) | C1 pool (PJ/y) | C1 load (MWh/h) |
|---|---:|---:|---:|---:|---:|
| Electricity | 90% | 4.953621 | 141.370467 | 5.530978 | 157.847548 |
| Natural gas | 90% | 7.999767 | 228.303841 | 13.126457 | 374.613501 |

The 100% rows remain context only. The four attempted rows are explicitly
labelled `selected_validation_failed_not_promoted`; they are not active inputs.

## Validation result

| Configuration and carrier | Explicit baseline (PJ/y) | Selected validation (PJ/y) | Anchor (PJ/y) | Baseline error | Selected error | Gate |
|---|---:|---:|---:|---:|---:|---|
| C0 electricity | 7.865499 | 12.323758 | 13.7 | 42.59% | 10.05% | improve |
| C1 electricity | 12.252357 | 17.230398 | 17.8 | 31.17% | 3.20% | improve |
| C0 natural gas | 4.500233 | 23.791746 | 12.5 | 64.00% | 90.33% | **fail** |
| C1 natural gas | 33.634336 | 45.467530 | 46.7 | 27.98% | 2.64% | improve |

This is not double counting. The 7.199790-PJ/y C0 NG baseload is additive and
constant, while the electricity baseload also increases internal generator
operation. C0 generator NG therefore rises from about 0.0624 PJ/y in the
explicit baseline to about 12.1542 PJ/y in selected validation. The resulting
cross-carrier response pushes total C0 named NG above its 12.5-PJ/y anchor.
HSM shares, the 24-hour policy, production-driven WAG generation, zero export,
steam, inventories and terminal handoffs remain unchanged or pass their
specified checks.

## HERACLES additions

The implemented C1 DRI reporting separates 8.1 GJ-LHV/t DRI reduction NG and
1.8 GJ-LHV/t DRI furnace NG and verifies their sum against the existing
9.9-GJ-LHV/t total. The existing 0.3-GJ-electricity/t-DRI value also verifies.
The LHV/HHV caveat remains unresolved.

VN25/IJM-01 85/15 remains operating-time evidence only. The DRI and EAF planned
outage ranges remain annual validation context, not calendars or dispatch
constraints. Finite DRI inventory and terminal handoff continue to represent
cold-DRI decoupling. No minimum-fuel rule, transition minimum, bypass state,
steam coupling, oxygas storage or WAG-yield change was introduced.

## Held-out integrity and next gate

The corrected governed runner stops before Stage D, records zero held-out
models and prohibits reselection. During development, an earlier local
orchestration defect opened the old held-out scratch cases before checking the
selected-validation gate. Those results are excluded from governed evidence
and cannot support a pristine held-out claim; no parameter was retuned from
them.

A revised freeze gate requires explicit user approval because it changes the
prescribed selection method. The narrowest defensible revision is to evaluate
electricity and NG shares jointly on validation so electricity-induced
generator NG is included in candidate scoring, followed by newly frozen,
previously unseen held-out periods. Until that gate passes, retain the
explicit-model/HSM baseline, keep the attempted baseload contract nonpromoted,
and keep deterministic DA bidding and all later Phase 6 work blocked.

