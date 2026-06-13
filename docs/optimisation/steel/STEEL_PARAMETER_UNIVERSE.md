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

## Wave B Update

Wave B adds the first stable public-source layer for the Tata IJmuiden-inspired topology and validation scaffold.

The main conclusions are:

- stable public topology categories now exist for the current BF-BOF baseline and the default Phase 1 hybrid BF-BOF plus DRI-EAF case;
- validation-target classes now include site-level annual production, route-level annual production, scrap-share ranges, public emissions anchors, public energy-scale anchors, downstream sink anchors, and utility-buffer evidence;
- the default public closure-pair decision is BF7 plus KGF2 in Phase 1, with KGF1 retained in the default Phase 1 case;
- early closure of KGF1 and KGF2 is tracked only as an exogenous scenario flag, not as the default future topology;
- MER Deel B is the controlling public technical source when simplified Tata webpages conflict with it.

### Wave B Source Hierarchy Rule

For Wave B topology and validation work, use this order:

1. MER Deel B and closely linked formal public reports;
2. annual reports and realised public reporting;
3. JLOI / basic-engineering / formal project-status pages;
4. general Tata explainer webpages;
5. research memos as discovery aids only.

### Wave B Unresolved Categories

Wave B does not resolve:

- exact recipes and yields;
- quality windows and product-mix routing;
- annual-to-hourly translation methodology;
- internal WAG valuation and dispatch rules;
- ETS and free-allocation treatment;
- contracted connection capacity and network tariffs;
- CCS operational availability;
- market-layer inputs for DA, stochastic, CVaR, or later reserve work.

Those remain for Waves C, D, and E.

## Wave C Update

Wave C adds the generic technology-range and annual-to-hourly methodology layer needed before any S2 steel LP can be scoped credibly.

The main conclusions are:

- S2 remains a deterministic hourly material-flow LP for the metallic network, not an energy, market, or risk model;
- public annual values stay as validation anchors or candidate ranges and do not become direct hourly operating truth;
- annual-to-hourly translation requires explicit availability and utilisation assumptions;
- BF and DRP are continuity-driven assets in S2 and therefore use narrow hourly envelopes;
- BOF and EAF are batch-equivalent assets in S2 and must not be treated as fully continuous dimmers;
- HDRI is a short-transfer class, while CDRI or HBI can be more storage-like only with explicit physical caveats;
- slab and WIP treatment requires endpoint rules and, where relevant, reheating or loss proxies;
- detailed WAG dispatch, ETS, internal transfer values, energy-cost-emissions, DA bidding, stochastic/CVaR, quarter-hour, `D_plus_4`, and `mFRR` remain postponed.

### Wave C Source Hierarchy Rule

For Wave C technology and methodology work, use this order:

1. high-quality public technical references and sector studies;
2. generic technology documents and established industry references;
3. educational or vendor material only as supporting context for handling classes or broad ranges;
4. research memos as discovery aids only.

### Wave C Candidate Range Categories

Wave C candidate evidence is organised around:

- BF hourly-envelope families;
- BOF metallic-mix envelope families;
- DRP quality bands and continuity-driven envelope families;
- EAF charge-envelope and batch-equivalent logic families;
- HDRI versus CDRI or HBI handling classes;
- downstream hot-route versus cold-route penalty or proxy families;
- annual-to-hourly translation methods;
- S2 validation-check definitions and infeasibility-diagnostic definitions.

### Wave C Annual-To-Hourly Translation Rule

Every annual public value used in S2 design must be interpreted through explicit method rows such as:

- calendar average throughput;
- available-hours calculation;
- online-average throughput;
- central, conservative, and flexible envelope variants;
- continuity-driven versus batch-equivalent translation rules;
- terminal-inventory neutrality rules.

Without those translation assumptions, an annual public value is not eligible to become an hourly candidate envelope.

### Wave C Minimum S2 Parameter Set

The minimum S2 material-flow LP parameter set now requires:

- topology and route configuration from Wave B;
- production target policy;
- continuity-driven BF and DRP envelope methodology;
- batch-equivalent BOF and EAF treatment;
- metallic-mix and route-share candidate logic;
- DRI and slab or WIP buffer classes;
- terminal-inventory neutrality rules;
- coarse downstream sink treatment;
- validation-check definitions and infeasibility-diagnostic definitions.

### Wave C Explicitly Postponed Layers

Wave C still does not approve or resolve:

- site-specific recipes and yields;
- detailed WAG dispatch;
- energy-cost-emissions accounting;
- ETS or free-allocation logic;
- internal gas or utility valuation;
- DA bidding and settlement;
- stochastic DA and CVaR;
- quarter-hour and `D_plus_4`;
- `mFRR`.

## Wave D Update

Wave D adds the first governed internal-energy and emissions scaffold for the future S3 steel layer.

The main conclusions are:

- the recommended minimal S3 is `B_lite`: a semi-detailed WAG layer with explicit `BFG`, `COG`, and `BOF_or_LD_gas` carriers;
- WAG generation must be linked to S2 throughput through public or generic coefficients rather than treated as an exogenous credit;
- natural-gas import and electricity import must be explicit from the start of S3;
- flare or spill variables with non-zero penalty logic are required to stop free disposal;
- Vattenfall remains an exogenous interface in minimal S3, not a full dispatch plant;
- internal WAG value must come through explicit useful-energy substitution, especially natural-gas replacement, and not through direct electricity-price valuation;
- the first emissions architecture must avoid double-counting WAG carbon and keep ETS or free-allocation detail postponed.

### Wave D Source Hierarchy Rule

For Wave D internal-energy and emissions work, use this order:

1. formal public technical Tata sources and public annual reporting for topology and interface directionality;
2. high-authority public technical references for generic WAG generation, composition, and integrated energy-system structure;
3. formal EU ETS or MRV sources for accounting rules and waste-gas treatment;
4. supporting industry case material only for structural guidance on holders, flare logic, and coupled utility systems;
5. research memos as discovery aids only.

### Wave D Minimal S3 Recommendation

The recommended first S3 layer is `B_lite`, which means:

- separate `BFG`, `COG`, and `BOF_or_LD_gas` balances;
- explicit natural-gas and electricity imports;
- optional simple `BOF_or_oxygas` holder logic where public structure exists;
- explicit flare or spill variables;
- a simple Vattenfall interface;
- a first emissions-accounting layer with captured-CO2 visibility.

It does not mean:

- a full mixed-gas network;
- a full steam or oxygen network;
- a full CHP or Vattenfall dispatch model;
- a full ETS or free-allocation model.

### Wave D Carrier-Specific WAG Treatment

Wave D candidate evidence now separates:

- `BFG` as the blast-furnace residual gas carrier;
- `COG` as the coke-route gas carrier;
- `BOF_or_LD_gas` as the converter gas carrier with holder relevance;
- optional later `mixed_gas` treatment for calorific control;
- natural-gas import as the main explicit external substitution carrier;
- electricity import and the Vattenfall interface as explicit boundary objects.

### Wave D Internal Energy Valuation Hierarchy

The governing valuation order is:

1. explicit useful-energy substitution, especially natural-gas replacement;
2. non-zero flare or spill penalty;
3. later sensitivity-only conversion value through explicit on-site generation paths if those paths are modelled;
4. never direct electricity-price valuation of WAG without explicit conversion logic;
5. never confidential transfer-price assumptions in the public scaffold.

### Wave D First Emissions Architecture

The first S3 emissions layer should keep separate:

- direct process emissions where relevant;
- WAG combustion or flare emissions;
- natural-gas combustion emissions;
- captured CO2 from the DRI route;
- optional indirect electricity emissions as a reporting-only module.

The critical architecture rule is that WAG carbon is counted once through a consistent boundary rule and never both at generation and at later use.

### Wave D Explicitly Postponed Layers

Wave D still does not approve or resolve:

- detailed mixed-gas setpoints and calorific-control constraints;
- full steam-network and oxygen-network scheduling;
- detailed Vattenfall or internal CHP dispatch;
- confidential internal transfer prices;
- detailed ETS or free-allocation treatment;
- DA bidding, stochastic DA, CVaR, quarter-hour, `D_plus_4`, and `mFRR`.

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
