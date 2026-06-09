# mFRR Capacity Flexibility-Envelope Interface Review V1

## Purpose
This note reviews the long-term architecture for Dutch incident-reserve / `mFRRda` capacity deliverability in the optimisation stack.

The goal is to keep the market module asset-agnostic and to treat the current hydrogen implementation as a temporary envelope generator rather than as the permanent market formulation.

This note does not change formulation or results. It freezes the methodological direction for the next refactor.

## A. Separation Principle
The `mFRR` capacity market module should only require:
- daily offered capacity decisions by direction
- daily bid-price candidate decisions by direction
- acceptance-threshold scenario data
- expected capacity-revenue coefficients
- a time-indexed physical flexibility envelope

The market module should not hard-code electrolyser, compressor, or later steel-plant process logic.

The physical model should produce the flexibility envelope. The market module should only consume it.

## B. Long-Term Flexibility-Envelope Interface
Preferred site-level interface for each dispatch period `t`:
- `site_upward_flexibility_mw[t]`
- `site_downward_flexibility_mw[t]`

Optional asset-level interface for multi-asset extensions:
- `asset_upward_flexibility_mw[a, t]`
- `asset_downward_flexibility_mw[a, t]`

Proposed aggregation principle:
- `site_upward_flexibility_mw[t] = aggregate_upward_flexibility(asset_upward_flexibility_mw[:, t])`
- `site_downward_flexibility_mw[t] = aggregate_downward_flexibility(asset_downward_flexibility_mw[:, t])`

Important caveat:
- simple summation is only valid if shared resource constraints, mutual exclusivity, network limits, buffer limits, and non-overlap conditions are already enforced in the physical model
- otherwise the site envelope must be computed through a tighter aggregation rule than plain summation

This keeps the market layer stable when the physical asset model becomes more complex.

## C. Capacity-Only Deliverability Constraints Using The Envelope
For capacity-only `v1`, the market module should enforce daily capacity obligations against the time-indexed site envelope.

For every delivery day `d` and every period `t` inside that day:
- `offered_capacity_up[d] <= site_upward_flexibility_mw[t]`
- `offered_capacity_down[d] <= site_downward_flexibility_mw[t]`

Interpretation:
- the accepted daily capacity product must remain physically deliverable throughout the contracted delivery day
- the market module does not need to know which asset or process provides the flexibility

This is the preferred long-term formulation boundary.

## D. Mapping The Current Hydrogen Proxy Into The Envelope Framework
The current hydrogen implementation can be reinterpreted as a temporary site-level envelope generator.

Current implied envelope:
- `site_upward_flexibility_mw[t] = P_el[t] + P_comp[t]`
- `site_downward_flexibility_mw[t] = electrolyser_nominal_mw + compressor_max_mw - (P_el[t] + P_comp[t])`

This mapping is useful because it preserves the current numerical behaviour while making the architecture explicit.

However, it is only a hydrogen-specific `v1` approximation.

Main caveats:
- it assumes electrolyser and compressor load are fully reducible or increasable within the capacity obligation
- it ignores ramping during reserve delivery
- it ignores activation duration
- it ignores minimum stable operation during actual activation
- it ignores process recovery after activation
- it treats compressor flexibility simplistically
- it is acceptable as a capacity-availability proxy only
- it is not proof of activation feasibility

The exact one-day comparison for `2025-07-11` remains useful here because it confirms optionality and objective consistency, but it does not validate this proxy as a final industrial flexibility representation.

## E. Architecture Options
### Option 1: Keep The Site-Load Envelope Hard-Coded In The Market Module
Assessment:
- simple for the current hydrogen pilot
- poor long-term architecture
- embeds asset-specific assumptions directly in market logic
- makes later multi-asset extension unnecessarily brittle

Conclusion:
- not recommended as the long-term design

### Option 2: Switch To An Electrolyser-Only Proxy
Assessment:
- easier to explain in the hydrogen case
- still asset-specific
- may be too narrow for a later multi-asset production facility
- could be useful as a hydrogen-only sensitivity case

Conclusion:
- not recommended as the main architecture
- acceptable only as a later sensitivity comparison if needed

### Option 3: Introduce A Flexibility-Envelope Interface
Assessment:
- best long-term architecture
- cleanly separates market mechanism from physical flexibility estimation
- supports future multi-asset industrial models
- keeps the `mFRR` market block stable while physical models evolve
- naturally supports later activation-aware extensions

Conclusion:
- preferred long-term architecture

### Option 4: Implement A Full Activation-Aware Flexibility Envelope Now
Assessment:
- methodologically strongest long-run target
- too large for immediate `v1`
- would pull activation timing, recovery, energy delivery, and sanctions into scope too early

Conclusion:
- defer to the later activation layer

## F. Recommendation
Recommended decision:
- adopt Option 3, the flexibility-envelope interface, as the long-term architecture
- keep the current hydrogen formula only as the first temporary envelope generator
- do not adopt the electrolyser-only proxy as the main architecture
- optionally allow an electrolyser-only proxy later as a sensitivity case
- do not implement a full activation-aware envelope yet

This recommendation preserves the current pilot while preventing hydrogen-specific assumptions from becoming the permanent market design.

## G. Practical Phased Implementation
### Phase 1: Documentation Reframe
- describe the current hydrogen deliverability rule as an availability-envelope constraint
- keep the current numerical formulation unchanged
- expect no solver-result changes

### Phase 2: Explicit Envelope Refactor
- introduce named expressions or helper functions in the optimisation model:
  - `site_upward_flexibility_mw[t]`
  - `site_downward_flexibility_mw[t]`
- connect the `mFRR` capacity constraints to those expressions instead of directly to `P_el[t] + P_comp[t]`
- treat this as a refactor, not a methodology change
- expect identical results in the current hydrogen test

### Phase 3: Multi-Asset Envelope Generator
- for a larger production facility, generate the envelope from all relevant assets and processes
- incorporate shared-resource constraints, buffer dependencies, and non-overlap logic in the physical layer
- keep the `mFRR` market module unchanged

### Phase 4: Activation Layer
- later add activation timing
- later add energy bid fulfilment and recovery
- later add imbalance or settlement consequences
- later add sanctions or non-delivery treatment if needed

## H. Thesis-Safe Wording
Suggested wording:

`The capacity-only mFRR bidding formulation uses an availability-envelope proxy for reserve deliverability. The market module is separated from asset-specific flexibility estimation. In the hydrogen test case, the site-level envelope is approximated from electrolyser and compressor operating levels. This provides a tractable capacity-availability representation for the pilot model, but does not claim activation-feasibility validation. Activation timing, recovery, and reserve-energy settlement are deferred to later model extensions.`

## I. Interpretation Of Current One-Day Evidence
The exact one-day comparison for `2025-07-11` showed:
- optional `mFRR` participation is feasible and economically optional
- under the tight exact setting, the model chooses `0.0 MW` Up and `0.0 MW` Down
- no `mFRR` capacity revenue is earned on that day

This supports the correctness of the optional market interface, but it does not justify freezing the current hydrogen proxy as the long-term architecture.

Weekly `mFRR` evaluation remains blocked until coherent multi-day DA scenarios are available.

## J. Next Task Recommendation
Recommended next task:
- `MFRR_CAPACITY_FLEXIBILITY_ENVELOPE_REFACTOR_V1`

Recommended scope:
- introduce explicit envelope expressions in `optimisation_model.py`
- keep numerical behaviour unchanged
- rerun the exact one-day comparison to confirm identical results
- do not wire command centre
- do not add activation
- do not change forecasting or scenario artifacts
