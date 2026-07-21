# C5 Remaining Process-User Controller Source Audit

## Purpose

C5p_r answers a narrow implementation question: whether the existing source
cards and upstream C5 layers contain enough information to reconcile the
remaining WAG/NG process users without reviving the aggregate-WAG fallback. It
is a source-to-controller readiness audit only. It does not create a new
allocator, alter C5p_o balances, edit source cards, or promote inputs.

## Answer

The repository has enough evidence for **three existing controlled diagnostic
controller surfaces**, but they must be reconciled before they can be used by
the newer authoritative C5p_o/q contract ledger:

- **KGF underfiring:** upstream COG self-use is explicit and quantitatively
  bounded, but its COG boundary must be reconciled before it is reflected in
  the newer contract ledger.
- **BF hot stove:** upstream BFG-first heat demand exists. Its 2.20 GJ/t HM
  demand remains development/sensitivity-only and needs a denominator/boundary
  reconciliation.
- **PEFA:** a total-gas controller exists upstream and its 24-hour annualised
  values explain the COG/BOFG gaps in C5p_q. Its horizon label must be made
  explicit before contract integration; no fixed stage split is allowed.

HSM/WBW and sinter already have accepted diagnostic outputs and should be
preserved. BOF auxiliary fuel remains sensitivity-only. C1 flare and
`mixed_wag` remain blocked for physical allocation.

## What this does not permit

- no `aggregate_wag` allocation;
- no numeric `mixed_wag` allocation or Wobbe claim;
- no C5p_k reuse as physical evidence;
- no invented WAG/NG ratio;
- no WAG/fuel-explicit CO2, economics, DA, or full sensitivity execution.

## Critical review

Review `process_user_controller_source_audit.csv` first. The critical rows are
KGF underfiring, BF hot stove and total PEFA gas heat. Then inspect
`unresolved_process_use_mapping.csv`: it shows that COG and BOFG gaps are still
gaps, not assignments. A future controller adapter is acceptable only if it
preserves C5p_o carrier balance and produces an explicit source/activity/mix
trace.

## Gate

- Existing-controller reconciliation for KGF, BF hot stove and total PEFA: GO,
  diagnostic-only.
- Physical allocation, NG residual policy, WAG/fuel-explicit CO2, sensitivity,
  migration, economics and DA: NO-GO.

Status: `source_to_controller_readiness_audited`. Thesis usability: `false`.
