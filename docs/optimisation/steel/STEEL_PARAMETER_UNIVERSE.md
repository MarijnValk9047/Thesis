# Steel Parameter Universe

## Purpose

This document defines the first governed parameter-universe scaffold for Phase S1.

It is a classification and governance surface, not a steel MILP implementation and not an approved value table.

The universe below is derived from:

- the steel planning documents in `docs/optimisation/steel/`;
- the Deepsearch 1 steel memo as a non-authoritative category-discovery aid.

The memo may inform category coverage, schema needs, and follow-up research waves. It must not be treated as stable evidence for approved parameter values.

## Status Boundaries

Keep these objects separate:

| Object | Meaning | May drive model directly |
|---|---|---|
| Model input | Explicit input field expected by loaders and configs | Only after approval |
| Constraint | Structural rule or bound the model must enforce | Only after the underlying input is approved |
| Objective parameter | Economic, emissions, or market coefficient used in the objective | Only after approval |
| Validation target | External plausibility anchor used to check outputs | No |
| Assumption | Explicit simplification, placeholder, or modelling choice | No, unless frozen for a phase and documented |
| Sensitivity-only parameter | Parameter reserved for robustness testing rather than base runs | No, unless used in a labelled sensitivity run |

## Governance Rules

1. No steel model parameter may be hardcoded in Python.
2. Approved model input tables are created only after candidate values are reviewed.
3. Category discovery is allowed before value approval.
4. Candidate ranges may exist without a point value.
5. Validation targets must stay distinct from approved operating inputs.
6. Non-authoritative research memo content must never be represented as stable source evidence.

## Modelling Layers

### Time And Market Structure

- Timestep set and granularity labels.
- Delivery horizon labels such as `D_only` and later `D_plus_4`.
- Forecast-origin and settlement-timing conventions.
- Scenario index and probability structures for later stochastic work.
- DA price and settlement parameters for later market layers.

Typical roles:

- model input;
- constraint;
- objective parameter;
- later sensitivity-only parameter.

### Site Boundary And Configurations

- Configuration identifiers for baseline BF-BOF and later Phase 1 hybrid.
- Route activation flags and allowed imports/exports across the model boundary.
- Residual-load policy and exogenous utility treatment.

Typical roles:

- model input;
- constraint;
- assumption;
- validation target.

### Production Target And Product Mix

- Production target definition for each phase.
- Route share targets used only for validation or sensitivity where needed.
- Product-family mix and downstream demand representation.

Typical roles:

- model input;
- constraint;
- validation target;
- sensitivity-only parameter;
- assumption.

### Process-Unit Operating Parameters

- Throughput bounds.
- Minimum stable load, ramping, and later commitment needs.
- Availability and outage indicators.
- Shared downstream sink capacities.

Typical roles:

- model input;
- constraint;
- validation target;
- assumption.

### Material Conversion And Yields

- Route recipes and conversion factors for BF, BOF, DRI, EAF, casting, and rolling blocks.
- Yield, loss, and by-product coefficients.
- Quality-linked recipe windows reserved for later work.

Typical roles:

- model input;
- constraint;
- validation target;
- sensitivity-only parameter.

### Energy Carriers

- Electricity, natural gas, hydrogen, oxygen, nitrogen, steam, water, and compressed-gas categories.
- Carrier-level units, storable flags, and import policies.
- Energy-intensity coefficients by process block.

Typical roles:

- model input;
- objective parameter;
- constraint;
- validation target.

### WAGs And Internal Gas Network

- BFG, COG, BOF/LD gas, mixed-gas categories, and internal allocation logic.
- Holder levels, throughput limits, and flare or spill treatment.
- Opportunity-value conventions reserved for later review.

Typical roles:

- model input;
- constraint;
- objective parameter;
- assumption;
- sensitivity-only parameter.

### Buffers, Stores, And Inventory

- Scrap, DRI, slab/WIP, oxygen, and gas-holder buffers.
- Initial policy, terminal policy, loss terms, and throughput limits.
- Anti-arbitrage rules to stop free-battery behaviour.

Typical roles:

- model input;
- constraint;
- assumption;
- validation target.

### Thermal And Quality Degradation

- Residence-time or dwell constraints where hot/cold state matters.
- Storage penalties or degradation proxies.
- Quality-window restrictions for scrap and DRI usage.

Typical roles:

- constraint;
- assumption;
- sensitivity-only parameter;
- later validation target.

### Electricity Connection And Network Costs

- Import/export bounds.
- Technical and contracted connection capacity.
- Capacity-charge, network-tariff, and peak-cost categories.
- Loss factors and later congestion assumptions.

Typical roles:

- model input;
- objective parameter;
- constraint;
- validation target;
- sensitivity-only parameter.

### Emissions And ETS

- Direct and indirect emissions-factor categories.
- Captured CO2 accounting categories where relevant.
- ETS convention, free-allocation treatment, and later CBAM interface.

Typical roles:

- model input;
- objective parameter;
- validation target;
- assumption;
- sensitivity-only parameter.

### Financial And Commercial Parameters

- Raw-material price categories.
- By-product credit or disposal categories.
- Utility, electrode, refractory, and operating-cost families.
- Product-value and shortfall-penalty categories.

Typical roles:

- objective parameter;
- model input;
- assumption;
- sensitivity-only parameter.

### DA Bidding And Settlement

- Submitted quantity, bid-price policy, or cleared-consumption-policy inputs.
- Clearing, procurement, and settlement parameters.
- Realised-vs-optimisation-stage reporting requirements.

Typical roles:

- model input;
- objective parameter;
- constraint;
- validation target.

### Stochastic / CVaR

- Scenario identifiers and probabilities.
- Non-anticipativity set definitions.
- VaR, excess-loss, confidence-level, and risk-weight parameters.
- Scenario diagnostics and containment indicators.

Typical roles:

- model input;
- objective parameter;
- constraint;
- validation target;
- sensitivity-only parameter.

### Later `mFRR`

- Reserve-capacity and activation-logic families.
- Deliverability bounds, rebound logic, and penalty categories.
- Later market-settlement fields separate from DA-only inputs.

Typical roles:

- later model input;
- later objective parameter;
- later constraint;
- later validation target.

### Validation Targets

- Public throughput anchors.
- Public route-volume anchors.
- Aggregate energy-demand plausibility ranges.
- Public connection and emissions anchors.
- Solver-scale and tractability expectations.

Typical roles:

- validation target only.

## What This Enables

This scaffold is intended to support:

- parameter-universe maintenance in `parameter_universe.csv`;
- source-card creation from stable references only;
- later candidate-register work;
- later approved model input tables;
- explicit separation between evidence, assumptions, and model-use status.

## What This Does Not Approve

This scaffold does not approve:

- any steel parameter value;
- any steel model input table for direct optimisation use;
- any Deepsearch citation as thesis evidence;
- any steel MILP implementation choice beyond the already frozen planning scope.
