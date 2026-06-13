# mFRR Capacity One-Day Reporting Cleanup V1

## Purpose
This note freezes the correct interpretation of the current one-day Dutch incident-reserve / `mFRRda` capacity pilot outputs for `2025-07-11`.

It prevents older relaxed-gap smoke outputs from being reused as economic conclusions.

## A. Result Hierarchy
### 1. Relaxed-gap smoke result
Run family:
- `20260606_195136_mfrr_capacity_one_day_smoke_v1`
- downstream summaries built from that run

Status:
- useful for mechanical model-construction verification only
- not valid for dominance or economic conclusion

Observed result under relaxed MIP gap:
- solver setting used the looser smoke tolerance
- model returned an incumbent with:
  - `Up = 5.5 MW`
  - `Down = 0.0 MW`
  - expected `mFRR` capacity revenue `= 47.245 EUR`

Interpretation rule:
- this result must be treated as a relaxed-gap incumbent, not as the final economic optimum for the day

### 2. Optionality dominance debug
Run families:
- `20260607_091016_mfrr_capacity_optionality_dominance_audit_v1`
- `20260607_092141_mfrr_capacity_optionality_dominance_audit_v1`

Status:
- these are the runs that identified the misleading source of the earlier `5.5 MW` offer

Established findings:
- objective sense is minimisation
- zero `mFRR` participation is feasible inside the enabled model
- expected `mFRR` revenue linkage is correct
- the earlier dominance failure was caused by relaxed MIP tolerance, not by a formulation bug

### 3. Exact one-day comparison
Run family:
- `20260607_093921_mfrr_capacity_one_day_exact_comparison_refresh_v1`

Status:
- this is the currently valid one-day economic interpretation for `2025-07-11`

Established exact result:
- `no_mfrr_baseline = mfrr_forced_zero = mfrr_optional`
- objective values match within numerical tolerance
- production matches within numerical tolerance
- shortfall matches within numerical tolerance
- optional `mFRR` chooses:
  - `Up = 0.0 MW`
  - `Down = 0.0 MW`
- expected `mFRR` capacity revenue `= 0.0 EUR`

## B. Correct One-Day Interpretation
Correct interpretation for `2025-07-11`:
- under the exact setting, the model does not bid `mFRR` capacity
- no `mFRR` capacity revenue is earned
- production and shortfall match the no-`mFRR` baseline exactly for this day
- optionality and objective dominance are satisfied

What this means:
- the enabled `mFRR` block is now behaving as an optional extension on this one-day test
- the earlier `5.5 MW` result should not be reused as the current economic result for the day

What this does not mean:
- it does not prove `mFRR` capacity is unattractive in general
- it only says that, on `2025-07-11`, the exact one-day model does not find a profitable capacity offer under the current capacity-only proxy

## C. Invalid Interpretations To Avoid
Do not claim:
- that `5.5 MW` Up reserve is the economically optimal result on `2025-07-11`
- that `mFRR` capacity is profitable on `2025-07-11`
- that the one-day smoke run validates a weekly `mFRR` strategy
- that activation feasibility is validated
- that `MARI` or `aFRR` are included

## D. Remaining Methodological Status
Current status:
- the capacity-only formulation passes optionality dominance on the one-day test
- a deliverability-proxy review can now be treated as a separate methodological question
- weekly `mFRR` evaluation still requires coherent multi-day DA scenario trajectories
- activation, 15-minute energy bids, imbalance settlement, and sanctions remain out of scope

## E. Current Reporting Rule
For thesis-facing or internal economic interpretation of the one-day test:
- use the exact-comparison run as the current valid source
- keep the relaxed-gap smoke result only as mechanical lineage
- mention explicitly that `2025-07-11` remains a one-day mechanical validation, not week-level evidence
