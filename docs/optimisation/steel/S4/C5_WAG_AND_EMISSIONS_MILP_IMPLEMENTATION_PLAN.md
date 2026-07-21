# C5 WAG, Emissions and Anchor-Sensitivity Implementation Plan

## Decision in one sentence

Build WAG first as a carrier-specific physical MILP layer, add only
double-counting-safe explicit fuel emissions second, validate both against the
canonical anchor register, and run a small staged sensitivity design only
after the physical and carbon-boundary tests pass.

This plan deliberately does **not** use residual electricity, residual NG, or
the Scope 1 gap as a load, fuel allocation, slack variable, objective term or
calibration target.

## Starting point

The current C5 baseline already has three useful diagnostic foundations:

- C5p_o: carrier-specific WAG diagnostic interface; BFG, COG and BOFG are
  quantitative only where their current rows preserve them.
- C5p_v: model-wide explicit-fuel CO2 subtotal; represented WAG combustion plus
  named modelled NG only.
- C5p_w: no BF, BOF, KGF, PEFA, sinter, EAF or DRP aggregate/process value can
  safely be added to that subtotal today.

The initial emission result is therefore a **partial explicit-fuel ledger**,
not full-site Scope 1, an ETS ledger or an economic carbon-cost layer.

## Non-negotiable model policies

1. Model physical WAG carriers separately: `BFG`, `COG`, `BOFG`.
2. Do not create a quantitative `mixed_wag` carrier. Wobbe index, gas quality
   and gas-network composition constraints are out of scope.
3. Do not use `aggregate_wag` for a physical sink. It is reporting only.
4. Use WAG first only where the existing controller eligibility permits it.
   NG can meet remaining demand only where the same accepted controller has an
   explicit NG route. No fixed WAG/NG ratio is invented.
5. Keep C5p_k's aggregate-WAG allocation out of the physical model; it remains
   warning/context evidence only.
6. Count a unit of WAG carbon once, at the represented point of oxidation.
7. Never add an aggregate BF/BOF/KGF/PEFA/sinter/EAF counter to the same total
   as overlapping explicit fuel carbon.
8. Keep DRP capture as a separate reporting flow until capture, transport and
   final sink are explicitly modelled.
9. Anchors validate and score diagnostics; they never become dispatch
   constraints or objective rewards.

## Phase 1 — Carrier-specific WAG MILP integration

### Objective

Move the accepted existing WAG-controller behaviour into one reusable MILP
surface without creating a universal gas pool or new gas-mixing physics.

### Model scope

Use a common carrier/sink structure for the current represented assets:

```text
carriers = {BFG, COG, BOFG}
sinks    = {mandatory process/self-use, HSM/WBW, sinter, PEFA,
            steam/boiler, generator interface, flare, residual reporting}
```

The exact sink list is conditional on an existing, source-backed controller or
eligibility row. An asset without one stays blocked rather than receiving an
invented route.

### MILP objects

For configuration `c`, time step `t`, carrier `g` and accepted sink `s`:

```text
wag_to_sink[c,g,s,t] >= 0       LHV energy allocated through an eligible route
wag_flare[c,g,t] >= 0           carrier-specific flare where a carrier split exists
wag_residual[c,g,t] >= 0        visible reporting residual, never reused
ng_to_sink[c,s,t] >= 0          only for an explicit existing NG-enabled route
```

Core constraints:

```text
WAG_generation[c,g,t]
 = sum_s wag_to_sink[c,g,s,t] + wag_flare[c,g,t] + wag_residual[c,g,t]

sum_g wag_to_sink[c,g,s,t] + ng_to_sink[c,s,t]
 = fuel_demand[c,s,t]

wag_to_sink[c,g,s,t] = 0  when carrier g is not eligible for sink s
ng_to_sink[c,s,t] = 0     when sink s has no accepted NG route
```

Existing controller rules must be represented as constraints or fixed governed
profiles, not replaced by a global least-cost allocation. Examples include KGF
COG self-use, BF hot-stove self-use, PEFA eligibility, boiler routes and the
fixed generator interface.

### Deliberate abstraction

This is more detailed than Athanasiadis-style aggregate WAG accounting because
each physical carrier and sink is visible. It remains tractable because it
uses an energy basis and eligibility matrix rather than Wobbe/gas-quality,
volume composition, pressure or mixing-station physics.

`mixed_wag` may be reported as a label for a controller output, but it is not
a decision variable and cannot carry energy or CO2 independently.

### Required implementation artifacts

- One shared WAG input schema or source-backed parameter table, not parallel
  per-stage copies.
- One reusable model-builder module for WAG variables, balances, eligibility
  and reporting expressions.
- A `wag_carrier_sink_timeseries` run output and an annual carrier balance.
- A controller trace explaining which existing rule supplied every route.
- A machine-readable blocked-route register.

### Tests and gate

Pass all of the following before proceeding:

| Test | Pass condition |
|---|---|
| Carrier conservation | BFG, COG and BOFG each close at every time step within numerical tolerance. |
| Eligibility | Every positive carrier-to-sink flow is permitted by the accepted matrix. |
| No universal pool | No `aggregate_wag` or `mixed_wag` decision flow reaches a physical sink. |
| Controller preservation | KGF, BF/hot-stove, PEFA, sinter, boiler and generator rules reproduce the accepted current controller output for a frozen diagnostic case. |
| C0/C1 topology | C1-only assets are absent from C0; C0/C1 WAG generation changes follow active asset topology. |
| No reuse | Carrier energy allocated to a sink cannot later reappear as residual, generator input or another sink input. |
| Fallback discipline | NG is zero at a sink unless its existing controller permits NG and eligible WAG cannot satisfy the modelled demand. |
| No economic leakage | WAG generators only offset internal electricity where already modelled; no WAG market/export revenue is introduced. |

**Phase-1 thesis gate:** WAG is acceptable for the physical MILP only when all
tests pass and every active route has an accepted source/controller basis. It
is still not a full gas-network model or a claim about actual Tata gas mixes.

## Phase 2 — Explicit fuel-emissions layer

### 2A. Add the current safe accounting mode to the MILP

Attach emissions as transparent expressions of already represented fuel use:

```text
CO2_WAG[c,t] = sum_(g,s) wag_to_sink[c,g,s,t] * EF_WAG[g]
CO2_NG[c,t]  = sum_s ng_to_sink[c,s,t] * EF_NG
CO2_explicit[c,t] = CO2_WAG[c,t] + CO2_NG[c,t]
```

Rules:

- Factors use the governed LHV-based RVO selections already used by C5p_u/v.
- WAG is counted once at combustion/flaring sinks only.
- Named modelled NG is counted once at its sink only.
- C1 flare contributes only if it becomes carrier-split; otherwise it remains
  a visible coverage gap.
- This expression is a reporting constraint/metric first. Do not add ETS cost
  or make the objective emission-minimising in this phase.

### 2B. Add non-fuel/process components only after source separation

The following are explicitly **not** added now:

| Asset | Why blocked | Minimum evidence needed |
|---|---|---|
| BF | Aggregate counter overlaps BFG carbon. | BF non-BFG carbon split / consistent carbon balance. |
| BOF | Direct candidate can overlap BOFG carbon. | BOFG-free direct process component. |
| KGF | Aggregate counter overlaps COG combustion/self-use. | Non-COG coking emissions split. |
| PEFA | Aggregate midpoint may include WAG/NG and solid fuel. | Solid-fuel quantity + factor excluding represented WAG/NG. |
| Sinter | Aggregate counter can overlap COG/NG. | Coke-breeze/process component plus WAG/NG exclusion. |
| EAF | Aggregate range overlaps explicit NG and masks coke/electrode carbon. | Separate coke-breeze, electrodes and other direct-carbon terms. |
| DRP capture | Capture is not net emissions by itself. | Capture-to-sink boundary and permanence/use policy. |

Each future component must be introduced as a named row with unit, activity
basis, source locator, factor, carbon boundary and overlap key. It may not be
created by subtracting the explicit-fuel subtotal from an aggregate counter.

### Tests and gate

| Test | Pass condition |
|---|---|
| Regression to C5p_v | Frozen annual C0/C1 explicit-fuel totals match C5p_v before new source-separated components are approved. |
| Point-of-oxidation once | Each carrier/sink carbon flow has one and only one ledger row. |
| Aggregate exclusion | No aggregate process row enters the explicit-fuel total. |
| Capture separation | Capture is neither added nor subtracted from emissions automatically. |
| Residual separation | Residual NG/electricity has no inferred CO2. |
| Unit basis | Every factor and energy term is explicitly LHV/HHV-labelled and unit-tested. |
| Source provenance | Every executable emission factor has an accepted locator and source status. |

**Phase-2 thesis gate:** the result is thesis-usable as *modelled explicit
fuel-combustion emissions* when the above tests pass. It remains unacceptable
to call it total site Scope 1, ETS emissions or net emissions until the blocked
component boundaries are repaired.

## Phase 3 — Annual reconciliation and anchor acceptance

### Purpose

Verify that the physical layer has sensible annual consequences without tuning
the model to public totals.

### Required annual diagnostics

For C0 and C1, report raw value, active-scaled comparison where valid, signed
residual, residual share and provenance status for:

- production / liquid-steel and final-product proxy;
- BFG, COG and BOFG generation, process use, boiler use, generator use, flare
  and residual;
- gross electricity demand, internal generation/offset and grid import;
- named modelled NG and full-site NG residual KPI;
- explicit fuel CO2 and Scope 1 residual KPI;
- oxygen/steam checks where their boundary is coherent.

Official Tata/MER anchors are the first validation reference. Athanasiadis is
a Rank-3 model-precedent comparison; use its Table 8/9 values only with their
denominator and NG-basis caveats. Badarinath is a methodology/abstraction
reference, not a site-level calibration target.

### Acceptance conditions

The physical/emission layer is methodologically acceptable for a thesis MILP
when:

1. all Phase-1 and Phase-2 tests pass;
2. every executable parameter is source-backed, unit-consistent and tied to a
   named activity basis;
3. no residual is silently converted into fuel, electricity demand or CO2;
4. all anchor comparisons show raw values and caveats, not only a composite
   score;
5. residuals retain their sign, including negative values;
6. no interpretation claims agreement with an anchor when its boundary or
   denominator is incompatible;
7. the run remains computationally tractable at the intended horizon.

For the first steel MILP, tractable means hourly, one representative week or
24–168 hour diagnostic horizon, deterministic, continuous energy allocation
where possible, and only existing process binaries. Carrier-specific WAG adds
roughly `3 × sinks × time steps` continuous flows; that is manageable before
stochasticity. Do not add scenario dimensions, DA economics or reserve logic
until this deterministic gate passes.

## Phase 4 — Anchor-informed sensitivity analysis

### Principle

Sensitivity is a transparent diagnostic, not a search for a parameter set that
looks most like the anchors. The acceptance question is whether a
source-backed range changes results in the expected direction without breaking
carrier balances, feasibility or carbon boundaries.

### Design: staged, not combinatorial

Use three values only where a documented low/central/high range exists. Test
one coherent lever group at a time first:

1. **WAG generation and self-use:** BFG, COG and BOFG yields; KGF underfiring;
   BF hot-stove self-use; eligible controller demand.
2. **WAG sinks and conversion:** boiler/generator conversion and accepted
   process fuel demand, without changing eligibility.
3. **Non-WAG electricity:** HSM/WBW, BOF/OSF, KGF, DSP and ASU electricity
   candidates, only after `other_modelled_electricity` is decomposed.
4. **Named NG demand:** only source-backed existing NG consumers and their
   documented ranges; never residual full-site NG.
5. **Emission factors/components:** only after the component has passed the
   Phase-2 source-separation gate.

The first combined scenarios are limited to:

```text
baseline_current
WAG_low / WAG_central / WAG_high
electricity_low / electricity_central / electricity_high
named_NG_low / named_NG_central / named_NG_high
combined_accepted_central
```

Do not run a Cartesian product until each one-group test passes. A later
combined low/central/high set may contain at most three coherent cases, not
every possible combination.

### Required output per sensitivity run

- resolved parameter manifest with source/card/range status;
- carrier-specific WAG balance and sink mix;
- electricity gross/net/import breakdown;
- named NG, visible full-site NG residual and no residual allocation;
- explicit-fuel CO2, separate aggregate/capture context and Scope 1 residual;
- anchor comparison table with raw and normalised signed residuals;
- feasibility, constraint violations, solve time, variables and MIP gap;
- double-counting and policy warning register;
- plain-language run conclusion stating whether the case is reporting-only,
  sensitivity-only or eligible for a later migration proposal.

### Scoring and stopping rules

Use component-level scores, not one opaque optimum score:

- electricity gross-use residual;
- grid-import residual where coherent;
- WAG carrier generation/use residual;
- named NG and full-site NG residual (separate);
- explicit fuel CO2 / Scope 1 residual;
- production and denominator residual.

Weight official/MER anchors above Athanasiadis, and Athanasiadis above generic
source-card values. Penalise: double counting, blocked provenance, incompatible
denominators, negative balance residuals, bypassing a controller, or adding
aggregate carbon to explicit fuel carbon.

Stop and reject a case when it requires a blocked route, violates carrier
balance, activates `mixed_wag`, allocates residual energy, hides negative
residuals, or improves an anchor only by an unsupported parameter choice.

## What is thesis-acceptable at each maturity level

| Claim | Earliest acceptable gate |
|---|---|
| “The model tracks carrier-specific WAG use.” | Phase 1 passes. |
| “The model reports explicit fuel-combustion CO2.” | Phase 2A passes. |
| “The model reports source-separated non-fuel process CO2 for asset X.” | Phase 2B passes for that exact asset only. |
| “The model approximates full-site Scope 1 / ETS emissions.” | Only after every material gap, capture policy and boundary is accepted; currently not allowed. |
| “The model is physically plausible against annual anchors.” | Phase 3 passes with caveats stated. |
| “The result is robust to reasonable parameter uncertainty.” | Phase 4 passes on validation-style cases, before any final thesis test claim. |
| “The steel MILP supports economics/DA.” | Separate subsequent gate; not unlocked by this plan alone. |

## Suggested implementation order and repository discipline

1. Create one WAG model-builder interface and migrate existing accepted
   controller rows into it through tests, not by copying diagnostics.
2. Add the Phase-2A emission expressions and regression tests.
3. Add one annual reconciliation runner that consumes the MILP output.
4. Write the sensitivity design/config registry before running cases.
5. Run the staged sensitivity sequence with governed run folders only.

Each implementation phase should update the canonical WAG/emissions docs,
run-level manifest and tests. Generated run data stays local unless selected
as compact thesis-critical provenance. Do not create another parallel C5
output hierarchy.

## Current immediate next action

Before changing the MILP, make a narrow **WAG-to-model integration mapping**:
map every C5p_o accepted carrier/sink/controller row to its existing model
variable, constraint or missing interface. This identifies what can be reused
directly, what is reporting-only and what is genuinely absent. Only then
should a shared WAG model-builder module be created.
