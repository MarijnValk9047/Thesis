# C5 WAG Activity-Basis Audit

## Purpose

This diagnostic reconciles the active quota-driven C1 WAG ledger with the
historical C5p_m ledger. It reads the historical C5p_e activity register first,
then compares the historical and active generation intensities on that shared
activity basis. It does not tune a WAG generation coefficient, change
allocation, or turn aggregate WAG into a physical carrier.

## Current finding

For the current C1 comparison, the BF and BOF drivers are close to the active
run and the coking driver is close after coke-to-dry-coal conversion. However,
the `generated_or_supplied` field in C5p_e is constructed as process use plus
availability before steam. It is a controller-reconciled supply term, not gross
source generation. It is therefore not comparable to the active gross carrier
ledger. None of these findings is permission to tune a coefficient.

## Use

Run `run_s4_4c5p_az_wag_activity_basis_audit.py` after a governed C1 physical
run. Treat all output as local diagnostic evidence. A subsequent WAG change
requires a source-backed activity/controller correction, not anchor fitting.
