# C5 Phase 5J WAG-Electricity Closure Gate

## Decision

`phase5j_heldout_gate_failed_previous_freeze_reopened`

Phase 5J reopens the Phase-5I deterministic freeze. A narrow costing correction
removes the apparent conflict between a larger electricity baseload and the
1.9-PJ/y C0 generator-NG source component, but the selected 90% electricity
candidate does not pass the predeclared fresh held-out flare gate. Phase 6B
therefore remains blocked.

## Corrected defect

The C0 aggregate generator's physical NG use was included in deterministic cost
only when the retired full-site NG bridge was also enabled. Phase 5G and later
correctly disabled that bridge, which unintentionally made generator NG absent
from the represented cost objective. This allowed NG generation while usable
COG and BOFG were flared and invalidated the former rejection of the 20--90%
electricity candidates.

The correction activates `C0_NG_GENERATOR` cost whenever the aggregate generator
is enabled. The fixed and flexible bridge flows remain conditional on the legacy
bridge. Production physics, capacities, WAG yields, HSM policy, terminal rules,
steam accounting, zero export and the residual-NG/steam/direct-CO2 settings are
unchanged.

## Corrected validation sweep

The original four validation periods were rerun with central WAG yields and one
electricity share shared across C0/C1. Annual-equivalent results are:

| Electricity share | C0 electricity error | C1 electricity error | C0 generator NG (PJ/y) | C0 flare (PJ/y) | C1 flare (PJ/y) |
|---:|---:|---:|---:|---:|---:|
| 0% | 42.59% | 31.17% | 0.000 | 8.475 | 0.198 |
| 10% | 38.97% | 28.06% | 0.000 | 7.068 | 0.188 |
| 20% | 35.36% | 24.95% | 0.000 | 5.665 | 0.173 |
| 30% | 31.74% | 21.84% | 0.000 | 4.257 | 0.164 |
| 40% | 28.12% | 18.74% | 0.000 | 2.855 | 0.161 |
| 50% | 24.51% | 15.63% | 0.000 | 1.451 | 0.177 |
| 60% | 20.89% | 12.52% | 0.000 | 0.622 | 0.169 |
| 70% | 17.28% | 9.41% | 0.000 | 0.568 | 0.164 |
| 80% | 13.66% | 6.31% | 0.000 | 0.541 | 0.169 |
| 90% | 10.05% | 3.20% | 0.000 | 0.542 | 0.165 |

The selected 90% contract represents 4.458259041214191 PJ/y in C0 and
4.977880260670008 PJ/y in C1, or 141.37046680663974 and
157.8475475859338 MWh/h respectively. It remains a
`validation_selected_user_authorized_aggregate_electricity_baseload_abstraction`,
not an observed site profile or exact anchor plug.

## WAG-yield sensitivity

A single predeclared diagnostic reduced BFG, COG and BOFG yields uniformly by
5%. At the 90% electricity share it lowered validation C0 flare only from 0.542
to 0.468 PJ/y while reducing annual WAG production from 57.352 to 54.485 PJ/y
and increasing C0 grid purchase from 1.911 to 2.874 PJ/y. The residual flare is
therefore dominated by hourly and carrier-specific matching, not by an annual
WAG-production excess that a small uniform yield correction resolves. No WAG
yield change is promoted.

## Fresh held-out result

The fourth pre-frozen candidate period failed the existing five-local-day D+4
timestamp structure before any model was solved. It was replaced using timestamp
structure only; no price, dispatch, anchor or model result was inspected during
replacement. The resulting four-period contract was then opened once, without
share reselection.

All 56 C0/C1 terminal-aware rolling models are optimal. All native production,
material, carrier-WAG, steam, electricity, terminal, HSM and source-component
overlap checks pass. Annual-equivalent held-out results are:

| Metric | C0 | C1 |
|---|---:|---:|
| Electricity consumption (PJ/y) | 12.3237 | 17.2303 |
| Electricity anchor error | 10.05% | 3.20% |
| Generator NG (PJ/y) | 0.0000 | 0.0125 |
| WAG production (PJ/y) | 57.3523 | 25.4492 |
| WAG flare (PJ/y) | 1.0591 | 0.2467 |
| Grid purchase (PJ/y) | 2.0873 | 12.7962 |

The only failed acceptance row is C0 absolute flare: 1.0591 PJ/y exceeds the
predeclared 1.0-PJ/y robustness limit by 0.0591 PJ/y. The approximately
0.1-PJ/y source expectation remains materially lower. The limit is not relaxed
and the electricity share is not retuned after held-out inspection.

## Consequence and remaining blocker

The Phase-5I freeze decision is superseded. Phase 6A remains useful historical
evidence that the bidding, information-timing, benchmark and settlement plumbing
works on the former boundary, but it is not authority to start Phase 6B.

The remaining discrepancy is a short-timescale, carrier-specific balancing
problem: BFG, COG and BOFG availability does not always coincide with eligible
generator and boiler sinks. Another baseload or yield-calibration sweep would
not identify that mechanism. A new implementation gate would need an explicit,
source-backed treatment of gas-holder usable volume, composition, pressure and
energy basis, or a separately authorised carrier-buffer abstraction. HERACLES
supports holder topology and nominal volume but does not establish the required
operating-energy contract. Until then, the process/HSM model is retained and the
deterministic represented boundary is not frozen for stochastic execution.
