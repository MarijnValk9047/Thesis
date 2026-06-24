# S3.0c-a C1 Route Share and Same-Output Energy Profile

## Status

S3.0c-a did not create a C1 fixed profile or run a C1 WAG diagnostic. The C1 route split was a governed development blocker, not a solver-selected profile.

The C1 same-output comparison basis is the C0 fixed-profile liquid-steel output: 8150.6772 t liquid steel over the 24-hour development profile. The route-share policy register records the previous S2 auxiliary LP feasible retained BF-BOF share interval of 0.5471962 to 0.67988981, but no central route share is selected.

## Evidence Found

Canonical evidence supports C1 transition structure and WAG-boundary context:

- `STEEL-SC-0013` / `STEEL-WAG-EVID-0042`: public Phase 1 transition structure, including closure context for coke and gas plants and BF-route changes.
- `STEEL-SC-0017` / `STEEL-WAG-EVID-0046`: public Heracless/MER context reporting approximately 45% reduction in combustible gas to Vattenfall.

These rows are validation and context evidence. They do not provide all coefficients needed to construct a C1 same-output profile.

## Policy

C1 must keep the same total output as the C0/reference basis. The comparison must isolate the configuration change: lower retained BF-BOF and coking activity, higher NG-DRP/EAF activity, reduced WAG availability, higher natural-gas demand, and higher electricity demand.

The C1 route share may not be selected from:

- an arbitrary solver solution;
- the midpoint of the S2 feasible interval alone;
- a 50/50 route split;
- a WAG-maximising, gas-minimising, or electricity-minimising objective.

The intended C1 profile requires a source-backed route-share basis or defensible capacity bounds plus emissions-calibration context. The current evidence is incomplete.

## Current Blockers

The following C1 inputs remain unresolved in canonical source evidence:

- retained BF-BOF central route share for the same-output comparison;
- retained coking capacity or retained coking proxy share;
- DRP natural-gas demand coefficient;
- DRP electricity demand coefficient;
- EAF electricity demand coefficient;
- route-output conversion basis linking DRP/EAF throughput to liquid-steel output;
- C1 site-electricity demand cap from governed component loads.

Until those are selected, C1 WAG generation cannot be calculated from retained BF, BOF, and coking activity without inventing the missing route and energy basis.

## S3.0c-b Update

S3.0c-b supersedes the exact-route-share blocker with three user-selected same-output development scenarios:

- `c1_high_drp_eaf`: BF-BOF share 0.55 and DRP-EAF share 0.45.
- `c1_central`: BF-BOF share 0.61 and DRP-EAF share 0.39.
- `c1_low_drp_eaf`: BF-BOF share 0.68 and DRP-EAF share 0.32.

These scenarios are selected for development coverage of the prior S2 feasible envelope. They are not Tata-exact, not thesis-grade, and not fitted to an emissions target.

## Consequence

Three C1 same-output route/material/WAG-driver profiles are created in `s3_provisional_dev_input/fixed_profiles/`. They support WAG-generation-only validation. A full C1 central diagnostic remains blocked until DRP/EAF gas and electricity inputs, site-electricity cap, mandatory-process-demand, and steam/boiler-demand inputs are selected.

No DA price, route optimisation, settlement, export revenue, stochastic scenario, CVaR, mFRR, or product-revenue logic is introduced.
