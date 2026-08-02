# C6 Phase 6A Deterministic DA Bidding and Settlement Gate

## Decision

`phase6a_phase5k_deterministic_da_bidding_and_settlement_validated`

Phase 6A now wraps the frozen Phase-5K represented boundary. The deterministic
point-forecast quantity bid, mandatory price-insensitive comparator and isolated
perfect-foresight oracle evaluate 168 rolling models in total. All are optimal,
and all physical, information-timing, bid and settlement checks pass.

The earlier Phase-6A v1 result on the superseded Phase-5I boundary remains
historical plumbing evidence only.

## Frozen physical boundary

The market layer inherits, without reselection:

- the 90% fixed electricity baseload: 141.370467 MWh/h in C0 and 157.847548
  MWh/h in C1;
- the fixed 7-PJ/y NG service: 221.968544 MWh/h in both configurations;
- the C0/C1 WAG-yield multipliers 0.95/1.00;
- zero residual steam, zero export and unchanged HSM/terminal policies;
- the common 2.0-MtCO2/y residual as reporting-only, outside dispatch,
  settlement and ETS.

Both baseloads are fixed, non-dispatchable and non-price-responsive. Electricity
enters bids and settlement only through net grid import. NG remains represented
procurement cost and cannot be replaced by WAG or HSM action.

## Information and settlement contract

The executable point-forecast case optimises only with the governed D-D+4
`y_pred` information available at bid submission. Its net grid import becomes
a price-taking day-ahead purchase-quantity bid. Full acceptance is an explicit
deterministic abstraction: cleared and settled quantity equals the bid,
imbalance is zero, and realised `y_true` enters settlement only.

The EUR 80/MWh schedule is the price-insensitive comparator. The
perfect-foresight case is an ex-post upper-bound-performance/lower-bound-cost
oracle, marked `not_submitted_counterfactual`; it never enters the executable
information set. No export revenue, bid-price curve or imbalance market is
represented.

## Realised-price source supplement

The fresh period beginning 27 April 2025 contains three source-series gaps at
00:00-02:00 UTC. Fraunhofer ISE Energy-Charts gives EUR 95.60/MWh for all three;
its other 21 observations on the same day exactly match the governed Dutch
series. A three-row fingerprinted supplement is admitted for realised-price
settlement and the oracle only. It cannot enter `y_pred` or alter the frozen
physical contract.

## Benchmark result

Totals aggregate four 168-hour held-out periods per configuration and are not
annual claims.

| Configuration | Case | Grid purchase (MWh) | Electricity settlement (EUR) | Total represented settlement cost (EUR) |
|---|---|---:|---:|---:|
| C0 | Point forecast | 58,362.30 | 2,884,644.79 | 145,392,289.80 |
| C0 | Price-insensitive | 57,773.21 | 4,966,297.76 | 147,473,942.82 |
| C0 | Perfect foresight | 71,622.10 | 2,575,615.42 | 145,083,260.43 |
| C1 | Point forecast | 268,590.54 | 17,658,271.40 | 243,092,318.66 |
| C1 | Price-insensitive | 270,860.24 | 22,715,134.06 | 247,771,227.22 |
| C1 | Perfect foresight | 271,769.83 | 17,196,218.59 | 242,595,563.92 |

Relative to the price-insensitive comparator, point-forecast operation reduces
represented cost by EUR 2.082 million in C0 and EUR 4.679 million in C1. Oracle
regret is EUR 0.309 million and EUR 0.497 million, respectively. Bid/import and
settlement-cost identities close within governed tolerances, realised future
prices do not enter executable bids, and export remains zero.

## Next gate

The governed run is
`steel_c6_phase6a_phase5k_deterministic_da_bidding_settlement_v2_20260729`,
uses `output_policy=minimal`, and contains 16 compact files (about 1.54 MB).
Phase-6B scenario-contract design is authorized. Stochastic execution requires
explicit scenario probabilities, non-anticipativity and an expected-value
benchmark before CVaR; mFRR remains later.
