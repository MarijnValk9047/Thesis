# Project Decisions

## Purpose

This file freezes the current optimisation-scope decisions so later work does not have to reconstruct them from scattered reports, configs, or run folders.

These decisions describe the repository's current methodological position. They do not imply that all later phases are complete.

The single current C5 status and next-gate document is
`steel/S4/C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md`. Older C5
reports remain lineage evidence and cannot override the quota-driven policy in
this file merely because they are newer or labelled `canonical`.

## Active Default

The active implementation path is the fixed-reference C0/C1 steel model, not
the hydrogen test case. Its accepted surfaces are a reproducible price-free
physical baseline and an opt-in deterministic represented-procurement-cost
mode. The current operating contract is:

- deterministic; price-free in physical mode and price-valued only in
  `fixed_reference_cost` mode;
- rolling 168-hour planning horizon with a 24-hour execution block;
- hard cumulative final-product-proxy quota deadlines;
- those cumulative deadlines are lower bounds; overproduction caused by
  governed continuous-operation minima is allowed and reported rather than
  suppressed with a fixed production profile;
- material, carrier-specific WAG, steam and utility feasibility;
- fixed cumulative C0/C1 route-scenario bands with 24-hour execution
  deadlines; hourly plant availability, bounded throughput, inventories,
  carrier-specific WAG, steam, named NG, internal generation and grid import
  remain endogenous;
- residual electricity and NG reported, never filled or calibrated.

For active C0 Gate-1 operation, KGF1, KGF2, sinter, BF6 and BF7 remain on over
the planning horizon while throughput stays unfixed inside governed bounds.
BOF remains batch-equivalent and downstream remains bounded. The active C0
coke-chain interface is 1.285 t dry coal/t coke and 0.359 t coke/t hot metal,
loaded from the coking and blast-furnace source cards. These are traceable
development coefficients, not Tata-measured operating truth and not tuning
variables.

The 6.75 Mt/y active development target is also tested as a final-product-proxy
daily quota in a separate thesis-scale feasibility scenario: 18,493.150685 t
per 24-hour execution block, using a 365-day reporting year. This is a
configuration-scale feasibility test, not a claim that final-product proxy and
liquid steel are identical public denominators. The quota-driven model neither
fixes C0/C1 operating hours nor selects an empirical C1 route share; it keeps
only topology, capacity and physical-balance constraints.

The project reports endogenous liquid steel, imported slab and site final
product as separate measures.  In particular, the official C1 context combines
6.8 Mt/y liquid steel with 0.6 Mt/y imported slabs and 7.0 Mt/y final product.
Imported slab is an explicit external boundary if later activated, never a
residual, free store or upstream-output substitute.

## Scope And Sequencing Decisions

### 1. No exclusive group bids for now

Exclusive group bids are not part of the active thesis implementation scope.

Reason:

- the current thesis emphasis is forecast/scenario/granularity/horizon comparison;
- bidding-strategy variation is secondary at this stage.

### 2. Physical steel feasibility before energy markets

The rolling steel feasibility optimiser must be stable, explainable and
reportable before deterministic energy-cost optimisation, DA bidding, scenario
optimisation or `mFRR` is added.

Reason:

- the immediate blocker is physical route, utility and boundary completeness;
- market complexity cannot repair missing physical accounting.

### 3. Hydrogen is historical reference, not a steel prerequisite

The hydrogen test case remains useful for rolling-horizon quota and run-report
patterns, but it is not a prerequisite for the active steel model.

Reason:

- the steel physical workstream has already progressed beyond a toy-case
  handoff and has its own C0/C1 controller, WAG, steam and emissions gates;
- reusable scheduling and reporting patterns can be adopted without keeping
  hydrogen as the active scope.

### 4. WAG and residual policy

- BFG, COG and BOFG remain separate physical carriers where existing rows
  preserve them.
- `mixed_wag` is structural-only and `aggregate_wag` is reporting-only.
- Eligible WAG is used before named, explicitly permitted NG backup.  No WAG/NG
  split ratio may be invented.
- Electricity and NG residuals are reporting diagnostics, never hidden plugs,
  calibration variables or costs.
- WAG-explicit combustion CO2 and aggregate process-counter CO2 remain
  mutually exclusive reporting modes; no ETS-ready total is claimed.
- The active selected development LHV map is BFG 3.35, COG 18.7 and BOFG
  9.58 MJ/Nm3, loaded through the single S3 governed adapter.  Later
  source-card alternatives remain labelled sensitivity candidates; they do not
  silently override the active map until a dedicated factor-review decision is
  made.
- For the explicit C1 6.75-Mt/y feasibility diagnostic, HSM fuel uses the
  labelled carrier precedence `COG -> BFG -> BOFG -> NG` after mandatory
  carrier-specific sinks.  This is an Athanasiadis-informed development order,
  not a fixed gas mix, a Wobbe model, or a Tata operating claim.  The realised
  carrier-to-sink flows are always reported.

### 4A. Pre-economics anchor sprint stop rule

Pre-cost physical validation and post-cost operational validation are now
separate contracts.  The historical rule requiring four annual operational
anchor families below 7.5% is superseded as a cost-design readiness gate.  It
incorrectly required a price-free feasibility tie-breaker to reproduce annual
generator fuel, grid-import, WAG-allocation and flare outcomes that depend on
relative costs.

Before deterministic energy-cost design, validation instead requires:

- explicit material conversions, capacities, operating classes and product
  denominators;
- carrier-specific WAG generation and conservation;
- non-overlapping named electricity loads and the identity `gross = internal
  generation + represented grid import`;
- named NG consumers on one LHV basis, separate from the full-site residual;
- generator fuel/conversion/capacity identities;
- the accepted represented-steam demand/supply identity;
- exclusive Mode-B point-of-oxidation accounting; and
- visible residual electricity/NG that cannot enter dispatch or the future
  objective.

Annual generator NG, generator WAG allocation, grid import, flare and the
dispatch-dependent steam/generator split are post-cost operational-validation
quantities.  They remain reporting anchors until a deterministic cost objective
exists and may not be forced through physical duties, route bands or residual
plugs.

All aggregates derived from BOF/EAF/HSM/DSP/import reference bands are
`scenario_definition`, including liquid-steel and final-product aggregates.
Unit equality alone never makes a row comparable.  The corrected independent
primary pre-cost annual-anchor score is therefore zero; this is an evidence
coverage statement, not a physical-readiness failure.

The former four-family 7.5% and +/-15% sprint rules remain superseded
historical context.  Residual electricity and NG remain reported gaps, not
calibration plugs or future cost terms.

### 4B. Product denominator and imported-slab boundary

- `endogenous_liquid_steel_t` is the upstream production metric and is
  compared only with liquid-steel anchors.
- `site_final_product_t` is the downstream product metric and may include
  product made from explicitly bounded imported slab.
- Imported slab is a source-backed external material supply, not a store, a
  residual, or a contributor to endogenous liquid steel.
- The 6.75 Mt/y all-endogenous final-product test remains a useful stress case,
  but it is not silently treated as the full MER C1 site-product boundary.
- No imported-slab supply is activated before origin-tagged HSM/DSP routing is
  implemented.

### 4C. C1 BOF/EAF metallics and scrap-boundary policy

- C1 BOF and EAF scrap are separate material-consumption streams. They may not
  be collapsed into an unconstrained shared process coefficient.
- A BOF/EAF metallics diagnostic may use the source-backed BOF hot-metal and
  scrap recipe together with the EAF HDRI and scrap recipe only when separate
  BOF/EAF caps and a bounded site-total scrap ledger are active.
- The 1.9--2.8 Mt/y public site scrap range is a validation envelope. The
  rounded central 2.0-Mt/y BOF-plus-EAF consumption case is diagnostic context,
  not a silently attributed external/internal supply split.
- External scrap and internal reuse may be reported separately, but neither is
  allocated to BOF or EAF until a source-backed origin ledger exists.
- The BOF metallics correction is a conversion/interface repair, not authority
  to change BF, BOF or EAF capacity. Upper-envelope scrap cases remain context
  only and cannot be selected merely because they improve anchor fit.
- The public upper-envelope technical-capacity diagnostic reaches 7.525768
  Mt/y final-product proxy; the exact 6.75-Mt/y case is feasible with 2.022445
  Mt/y site scrap consumption.  These prove capacity within the stated source
  envelope only; they do not promote the upper envelope as the central case.
- Gate-2 central scrap governance follows MER Deel B Table 5.2: 1.9 Mt/y is
  the central site supply boundary, 1.0 Mt/y is the BOF consumer guardrail and
  1.8 Mt/y is the EAF operational upper guardrail. The EAF central recipe uses
  0.9/3.3 = 0.272727273 t scrap/t liquid steel. The 1.8-Mt/y EAF and 2.8-Mt/y
  site values are DRI-substitution variants at unchanged steel output, not
  extra melting capacity. Route guardrails and the site cap must remain
  distinct; they may not encode the same 1.9-Mt/y allocation twice.

### 4C-1. Gate-2 HSM material conversion

- The historical 1.10 t slab/t HRC value is a broad, unlocated development
  proxy and is not the active Gate-2 central conversion.
- Gate 2 uses 1.06 t slab/t HRC as a rounded development central. It follows
  independently from the MER 6.8-Mt/y liquid-steel, 0.6-Mt/y slab-import,
  5.5-Mt/y HSM-output and 1.5-Mt/y DSP-output boundary at the retained 1.05
  DSP development conversion. EU-BREF loss references and a JICA engineering
  design yield independently support lower slab/HRC ratios.
- The coefficient is input per unit HRC output and applies equally to all HSM
  origins. It excludes casting loss and its material difference remains an
  explicit internal loss/scrap diagnostic. The 1.10 value may be retained only
  as a labelled historical high-loss sensitivity.

### 4D. Gate-1 sinter and represented BF-burden basis

- The active sinter activity is iron-ore feed in `t_iron_ore/h`. It must be
  converted before entering the sinter inventory or any per-tonne-sinter fuel
  or electricity term.
- For Gate-1 development feasibility, the accepted source-card conversion is
  1.230 t sinter/t iron-ore feed, the rounded inverse of 0.813 t iron ore/t
  sinter. It is development-only and is not Tata-measured or thesis-final.
- The active BF coefficient remains 2.1041666667 t hot metal per tonne of
  represented sinter, equivalent to about 0.4752475 t represented sinter/t hot
  metal. It is a controlled development proxy for the represented sinter
  share, not a complete BF burden recipe.
- Pellets and direct ore remain outside the explicit BF material balance. Coke
  is balanced separately at 0.359 t/t hot metal; PCI remains a development
  utility/accounting term rather than a closed burden-flow balance. The BF
  proxy must not be changed solely to force feasibility.

### 4E. Gate-3 rolling-lineage annual reporting

- Annual physical and anchor rows must be derived from the accepted solved
  rolling lineage. Concatenated executed blocks may be annualised only as a
  reporting equivalent; they are not a simulated calendar year and retain
  initial-inventory and lower-bound-quota transients.
- Annualised physical accounting accepts at most 0.01 MWh/y of numerical
  round-off. Electricity, NG and Scope-1 boundary gaps remain reporting-only
  residuals and are never introduced as model inputs.
- The active 6.75-Mt/y target remains excluded as independent validation.
  Fewer than four boundary-compatible primary anchor families below 7.5%
  requires a reported coverage gap, not parameter fitting.

### 4F. Gate-4 reference-validation and corrected anchor contract

- `endogenous_feasibility` and `reference_validation` are separate modes. Both
  use the same p_af rolling mechanism; neither is a simulated calendar year.
- The C1 reference mode uses cumulative narrow bands for BOF, EAF, HSM, DSP
  and imported slab, scaled to the selected 6.75-Mt/y site-final-product proxy.
  Every defining production row is a scenario definition and is excluded from
  independent validation.
- C0 retains its executable Gate-1 topology in the reference comparison. Its
  HSM/DSP public rows remain non-comparable until an independently evidenced
  C0 downstream routing and output-conversion contract is executable without
  overriding the governed coke/capacity chain.
- HSM slab input, governed loss and HRC output must be reported separately.
  Unit equality does not establish comparability. Generator anchors may use
  only actual generator WAG and named generator NG; configuration/family
  scoring may not mask C0 with C1.
- The generator volume-envelope and 0.104-MWh/t-HRC electricity cases are
  source-bounded sensitivities only. Neither is promoted because it improves
  context-anchor proximity.
- Gate 4 passes physical execution but stops pre-economics at zero of four
  primary configuration/family pairs below 7.5%. Source/boundary evidence
  repair was required before deterministic cost-design planning. This stop is
  historical and is superseded by the completed boundary closure below.

### 4G. Final pre-economics boundary and future cost contract

The paired Gurobi run
`steel_final_pre_economics_boundary_acceptance_v2_20260716` is the accepted
final physical readiness lineage.  C0/C1 endogenous and reference modes each
complete seven 24-hour executions under 168-hour replanning.  All route,
material, origin, carrier-WAG, named electricity, named NG, generator, steam,
Mode-B and residual-exclusion checks pass.

The governed route and future-cost boundaries are machine-readable in the
existing component-ontology directory:

- `c5_route_boundary_contract.csv`;
- `c5_future_cost_boundary_contract.csv`.

The first deterministic objective may later minimise only represented external
energy procurement cost:

`represented net grid-electricity purchases + represented named NG purchases`.

It must use endogenous route mode without reference-validation bands and keep
all current quotas, material/origin balances, capacities, operating classes,
WAG balances, represented steam/utilities, inventories and rolling handoffs.
Residual electricity, residual NG, WAG purchase cost, internal-electricity or
steam revenue, product revenue, ETS, DA, stochasticity, CVaR and mFRR are
excluded from the first layer.

The cost objective is prepared but not active.  No price value or cost result
is populated by the accepted physical run.  The readiness decision is
`ready_for_deterministic_energy_cost_design`, not authority to implement
markets or later economics.

### 4H. Ex-post deterministic procurement-cost accounting

The derived diagnostic run
`steel_s2_ex_post_cost_accounting_v1_20260716` is the accepted first
cost-accounting lineage.  It reads only the endogenous executed blocks from the
accepted v2 physical parent: the first 24 hours of each of seven replans for C0
and C1.  It does not sum overlapping 168-hour plans, invoke a solver, change
dispatch or activate a cost objective.

The governed central development scenarios in
`c5_external_supply_costs.csv` price only:

- represented net grid import;
- each represented named-NG consumer exactly once; and
- actual imported slab delivered to HSM, never the annual import cap.

The result label is
`represented-boundary ex-post deterministic procurement cost`.  Gross and
component electricity demand, residual electricity/NG, BFG, COG, BOFG, steam,
internal generation, product output, raw materials and ETS have zero direct
cost in this phase.  Imported slab receives no upstream site burden.

All 18 run-level checks and 17 focused implementation tests pass.  The physical
parent fingerprint and physical-builder fingerprint are unchanged.  The next
gate is raw-material procurement-boundary closure for coking coal, PCI,
ore/pellets and purchased BOF/EAF scrap.  Endogenous route-cost optimisation
and the full procurement-cost objective remain `NO-GO` until both major
routes have adequate external-input cost coverage.

### 4I. Fixed-reference procurement cost and pre-DAM interface acceptance

The earlier 4G/4H stops are retained as historical lineage and are superseded
for the fixed-reference scenario only. The accepted contracts and decisions
are now:

- `c0_c1_mer_fixed_reference_v1` fixes cumulative C0/C1 route bands, not hourly
  profiles. Proportional cumulative bands at each 24-hour execution deadline
  prevent rolling front-loading while preserving endogenous hourly operation.
- Represented external purchases are net grid electricity, named NG, dry
  coking coal, PCI, represented sinter/PEFA ore, imported DR pellets,
  represented purchased scrap and actual imported slab. They are priced once
  from solved physical quantities. BF pellets remain an unrepresented scope
  gap and HBI is inactive.
- The objective is lexicographic: minimise represented procurement cost;
  preserve the optimum within EUR 0.01; then minimise the existing physical
  tie-breaker. No arbitrary physical penalty is mixed into euro cost.
- The price-free baseline remains separately executable. Reference-validation
  output cannot emit a cost result, and fixed-reference cost mode does not
  authorise endogenous route selection.
- `steel_s2_fixed_reference_deterministic_cost_v3_20260716` is the accepted
  central cost lineage. `steel_s2_post_cost_reconciliation_v2_20260716` is
  derived from that same solved lineage; it does not reconstruct a second
  canonical dispatch.
- Price sensitivities remain one-family-at-a-time plus all-low/all-high. The
  VN25 0.34 efficiency case is allowed only behind the explicit source-bounded
  sensitivity flag and remains inside the source-card 0.34-0.35 development
  range; central stays 0.345.
- Electricity prices enter through `price_series_id` and an information-safe
  rolling slice. The flat series reproduces the accepted central run exactly.
  The synthetic varying series validates indexing only and is not DAM evidence.
- The Phase-7 completion decision was `ready_for_future_DAM_price_integration`.
  It is retained as the pre-audit historical decision and is superseded by the
  final S2 acceptance decision below. Real DAM data, bidding, settlement,
  realised-future information, export revenue, ETS, stochasticity, CVaR and
  mFRR remain inactive.

There is no independent matching variable-procurement cost benchmark. Reported
EUR/t values are represented-boundary scenario results, not Tata total cost,
full production cost, profit, NPV or a business case.

### 4J. Final S2 acceptance, explanation and governance decision

The derived run `steel_s2_final_acceptance_explanation_audit_v1_20260717`
reuses the accepted physical, cost, reconciliation, sensitivity and
price-interface lineages without another dispatch. Its decision is exactly
`ready_for_governed_DAM_data_contract`. This is authority to specify and
validate governed Dutch DAM price and forecast inputs only; it is not
`DAM_ready` and does not activate bids, clearing, settlement or revenue.

The accepted central lineage remains
`steel_s2_fixed_reference_deterministic_cost_v3_20260716`. Every complete
168-hour C0/C1 plan produces exactly the selected 6.75-Mt/y final-product
proxy. The 6.78375-Mt/y reported rolling execution is the annual equivalent of
seven concatenated first 24-hour blocks. With flat prices, timing is degenerate
after the primary cost optimum; the existing positive inventory term in the
physical tie-break selects the early +0.5% edge permitted by the cumulative
fixed-reference route bands. It is not a duplicated quota, wrong inequality,
reporting error or numerical-tolerance effect. The envelope is retained.

The accepted fixed-reference config enforces C0 KGF1/KGF2, sinter and BF6/BF7
as fixed-on with bounded, unfixed throughput. Its optional C1 component-
ontology continuous-class override is disabled; C1 on-state and throughput
remain endogenous within the fixed-reference topology, route bands and
capacity constraints. This distinction must not be silently rewritten as C1
fixed throughput or a fixed hourly schedule.

The C0 and C1 waterfalls close exactly at EUR 34.154162 million and EUR
61.068469 million over the executed 168 hours. Their EUR 262.524/t and EUR
469.399/t values are not directly comparable total-production-cost results:
C0 and C1 have different fixed route portfolios, energy interfaces, imported-
slab and DR-pellet exposure, while BF pellets remain an explicit unrepresented
scope gap and HBI is inactive. No active represented external purchase is
silently free, but these gaps block a complete burden or endogenous route-
economic claim.

The remaining generator gaps are accepted validation limitations, not fitted
duties. VN25 NG remains zero versus 4.1 PJ/y because no governed rolling
minimum hours/load/blend exists and central NG-generated electricity is more
expensive than grid import. Generator WAG plus flare is 6.696078 PJ/y versus
10.6 PJ/y because the carrier-conserving rolling allocation first closes
source-backed process/self-use and WAG-first eligible sinks. Repair would need
a reconciled carrier-specific annual-to-rolling operating contract on the same
production and gas-network boundary. Neither anchor may be imposed as an
annual target, WAG/NG ratio or residual plug.

### 4K. Pre-DAM operational-boundary hardening supersedes the execution-bias decision

The validation lineage
`steel_s2_pre_dam_operational_boundary_closure_v1_20260720` adds cumulative
production progress to the rolling controller. Completed production is carried
as credit/debt into each later replan. The remaining local cumulative
deadlines and first execution-block progress target are adjusted by that
state. In that historical closure lineage procurement cost was the primary
objective, production progress the second tier and the physical inventory
tie-break third. Decision 4N supersedes that ordering for the active rolling
price-response path after longer held-out execution exposed loss of recursive
production feasibility. Hourly throughput, route shares and the governed
+/-0.5% feasibility envelope remain unfixed.

The corrected central C0/C1 executions annualise to 6.75 Mt/y (numerical
residual below 0.0002 t/y), rather than repeatedly selecting 6.78375 Mt/y.
Carrier-specific BFG, COG and BOFG source-to-sink ledgers close from those same
executed blocks; the maximum reconstruction difference is 0.000257 MWh from
six-decimal hourly reporting and the underlying model residual checks pass.
Generator WAG plus flare is 6.727462 PJ/y versus the 10.6-PJ/y MER scenario
anchor, and VN25 named NG remains zero versus 4.1 PJ/y. These anchors remain
unforced scenario/operating-context comparisons.

No reviewed source provides a VN25 minimum stable load, heat-rate curve,
ramp/start contract or outage availability. IJ01 is confirmed as CHP backup/
reserve, but its electricity/steam split, electric efficiency/capacity and any
heat-service obligation remain deferred. BF-grade pellet quantity and burden
origin also remain absent from the active BF routes. Represented external
flows are priced once, purchased scrap remains the explicit development
boundary without an internal origin loop, residual electricity/NG remain
unpriced, and HBI remains inactive.

Therefore the prior `ready_for_governed_DAM_data_contract` decision is
superseded by `DAM_data_contract_only_operational_gaps_remain`. A governed DAM
data/forecast contract may be developed, but deterministic DAM-dispatch design
is not yet authorised. It requires the missing VN25/IJ01 operating evidence
and an active BF-pellet physical/procurement contract or an explicit later
scope decision that excludes those assets/flows from the claimed comparison.

### 4L. Bounded VN25 development price response is accepted as an upper bound

The validation lineage
`steel_s2_vn25_development_price_response_v1_20260720` formalises three
generator modes and solves four information-safe rolling cases. The mandatory
`price_insensitive_reference` retains the accepted flat central treatment.
`development_price_responsive` permits VN25 hourly operation from zero to the
existing 350-MW development capacity at 0.345 electricity efficiency;
`bounded_generator_sensitivity` permits only the existing 0.34 efficiency
alternative. BFG, COG, BOFG and named NG remain separate eligible inputs,
electricity offsets represented grid import only, and export/revenue remain
disabled.

At the central NG price of EUR 55/MWh LHV, the analytical break-even is EUR
159.420290/MWh_e at 0.345 efficiency (EUR 161.764706/MWh_e at 0.34). In the
governed synthetic 100/220-EUR/MWh_e step case, VN25 NG is zero in all 84
below-break-even executed hours and positive in the 84 above-break-even hours;
VN25 reaches but never exceeds 350 MW. The flat responsive case reproduces the
same solved physical result as the price-insensitive reference. C0/C1 remain
at 6.75 Mt/y, carrier balances and all material/origin/steam/electricity/cost
identities pass, and IJ01 remains non-price-responsive with its quantitative
CHP split deferred.

Minimum stable load, startup/shutdown, ramping, outage availability and a
VN25 CHP/steam obligation are omitted development features, not numerical
zeros or site-truth claims. The resulting full within-hour flexibility is an
upper-bound abstraction, not historical VN25 validation. The 4.1-PJ/y VN25-NG
and 10.6-PJ/y generator-WAG-plus-flare values remain unforced post-run
validation anchors. That gate's accepted decision was
`development_VN25_price_response_ready`. It permitted the separate governed
DAM price-data/forecast-contract task now recorded in Decision 4M; it did not
itself authorise forecast-driven dispatch. Bidding, settlement, export/revenue
and stochastic market layers remain unauthorised.

### 4M. Governed D-D+4 point forecasts are accepted for deterministic price response

The integration lineage
`steel_s2_hourly_da_dplus4_point_forecast_integration_v1_20260720` governs the
external run `20260706_024807_lago_lear_six_year_benchmark`, model
`lear_lago_direct_dplus4_strict_no_future_1092`, feature variant
`LEAR_LAGO_DIRECT_DPLUS4_STRICT_NO_FUTURE` and lead days 0-4. The optimizer
receives only `y_pred`; origin and target timestamps remain explicit, source
hashes fail closed, `y_true` is ex-post only, and MAPE is prohibited as an
acceptance metric.

The forecast adapter uses the existing price-series interface and unified
rolling builder. Its explicit planning horizon is 120 hours with 24-hour
execution, seven daily replans and inventory handoff. A same-model flat
80-EUR/MWh pair has zero price and dispatch residual. Seven validation replans
and one frozen held-out seven-replan window pass with 70/70 Gurobi-optimal C0/C1
models, exact 6.75-Mt/y terminal production, material/origin conservation and
zero carrier-specific WAG residual. A fifth same-horizon price-insensitive case
retains the mandatory benchmark and passes the same guardrails.

Intermediate production credit/debt may use the governed +/-0.5% envelope,
but the final execution block now has a hard aggregate equality to the
remaining cumulative quota. This is a quota-deadline correction, not fixed
hourly production or a fixed route share. The decision is
`ready_for_deterministic_DAM_price_response`. It permits deterministic
point-forecast response analysis only; bidding, settlement, export revenue,
ETS, stochasticity, CVaR and mFRR remain unauthorised.

### 4N. Deterministic response is accepted with physical progress first and partial anchor coverage

The diagnostic lineage
`steel_s2_deterministic_price_response_anchor_diagnostics_v1_20260720`
supersedes cost-first lexicography for active rolling response. Cost-first
execution accumulated 343-528 t of C1 production credit and made a later
120-hour horizon infeasible despite unchanged source-backed capacities. The
accepted order is now minimum cumulative production-progress deviation,
represented procurement cost within that optimum, then the non-economic
physical tie-break. No physical parameter, route share, residual input or
price was changed.

Behavioural comparisons use complete first-window plans from the identical
initial state. The flat D-D+4 adapter matches the native 80-EUR/MWh path to
0.000000134 EUR; forecast dispatch weakly dominates the flat comparator on
the same y_pred for C0/C1 on validation and held-out splits; and the explicitly
labelled y_true perfect-foresight oracle weakly dominates forecast dispatch on
realised cost in all four comparisons. Operational optimisation remains
y_pred-only.

The checkpointed held-out run solves 180 replans and 4,321 actual timestamp
hours with 444/444 optimal Gurobi models. C0/C1 cumulative production,
material/origin conservation and carrier-specific WAG guardrails pass. The
support is only 49.326% of 8,760 and is therefore
`partial_year_not_annual`. Two Rank-1 rows are primary-comparable, but neither
is below 7.5%: VN25 NG is 0.6985 versus 4.1 PJ/y and generator WAG plus flare
is 7.0618 versus 10.6 PJ/y. These gaps remain unfitted validation evidence.

The decision is `price_response_valid_anchor_coverage_partial`. The next
permitted step is governed deterministic DAM-response interpretation. This is
not `DAM_ready` and does not authorise bidding, settlement, export revenue,
ETS, stochasticity, CVaR or mFRR.

### 4O. User-authorized full-site emulation is a separate overlay

The user-authorized full-site emulation reopening does not replace or mutate
the strict source-driven baseline. Checkpoint 1 freezes its accepted anchors,
explicit 5/15/25% background-electricity cases and permitted sensitivity
ranges in separate overlay contracts. The completed Checkpoint-6 held-out
evaluation retains the source-driven baseline as central and keeps
`recovery_bg25` as a nonpromoted `emulation_sensitivity_only` case. Its
independent decision is `complete`; the next bounded thesis gate is
terminal-inventory equivalence and a terminal-inventory value bridge before
any economic-uplift claim.

The later bounded DEVELOPMENT-only C0 mechanism experiment does not reopen
that held-out decision. With the physical interface structurally invariant,
lower NG activates named generator NG in the volatile cases but not in the
calm case. The builder tie-break penalizes flexible-heat NG but not generator
NG, so zero flexible NG is allocation-location non-identifiability rather than
proof of no substitution; realised WAG-generation spreads remain
endogenous-dispatch diagnostics rather than a parameter or promotion gate.
The source-driven baseline remains central, all repair candidates remain
nonpromoted, and the decision is
`lower_ng_activates_generator_ng_in_volatile_cases_allocation_location_tiebreak_selected_stop_no_second_search`.

Any later result remains a Tata IJmuiden-inspired full-site emulation, not an
exact digital twin. The Tata-facing questionnaire is a separate workstream,
and the physical and first-order full-site CO2 ledgers must remain separate.

### 4P. Phase-1 full-site boundary and anchor hierarchy is frozen

The user-accepted Phase-1 overlay supersedes earlier overlay classifications
when they conflict, while the strict source-ranked target and parameter
contracts remain unchanged. The 5/15/25% background cases and their YAML are
historical analytical-screen provenance only. Active C0 background classes are
25% low, 30% central and 31% high; 35-40% is excluded without new Tata
evidence. The primary real gross-electricity anchor is 3.154-3.170 TWh/y;
Athanasiadis Table 8 at 3.17 TWh/y is supporting model context.

The primary electricity-generation anchor is 2.528 TWh/y of real WAG-only
generator output. NG-generated electricity is excluded. Separate Athanasiadis
model precedents are approximately 2.74 TWh/y (Table 8) and 2.773 TWh/y
(Figure 91 interpretation). Natural gas uses one annual-calendar LHV
convention: fixed full-site NG is 8.005 PJ/y, flexible-heat NG may allocate
0-3.07 PJ/y within the separately conserved 3.07-PJ/y WAG-plus-NG heat
service, the primary real anchor is 9.666 PJ/y, and context values are
approximately 10.35 PJ/y (Figure 91) and 10.425 PJ/y (Table 8). No percentage
residual or NG plug is allowed.

Current represented total WAG remains approximately 57.3-57.5 PJ/y versus
approximately 54 PJ/y MER/Tata context, a difference of approximately +6%.
Phase 1 does not authorize movement of WAG yields or runtime coefficients.
Represented Mode-B/marginal emissions remain separate from a reporting-only
constant site-boundary sensitivity of approximately 1.7-2.0 Mt CO2/y used to
reconcile the partial represented boundary toward the accepted 12.24-Mt/y
first-order total. This bridge never enters dispatch, optimization,
procurement cost, CO2 pricing or marginal emissions.

Anchor interpretation uses one policy: within 5% is preferred; 5-10% is
acceptable only when physically and methodologically credible; above 10%
requires an explicit boundary or configuration explanation; and no single
anchor may be improved by materially worsening several others. The bounded
DEVELOPMENT diagnostic
`steel_c5_wag_ng_allocation_envelope_v6_20260726` passes 8/8 trajectories and
56/56 endpoints. Its certified represented-cost-optimal WAG-electricity
maximum is below 2.528 TWh/y in all four frozen cases. This is a boundary/result
finding, not a calibration objective or candidate-selection result; no
candidate is promoted.

### 4Q. Validation tolerances are unit- and purpose-aware

The canonical steel validation contract is
`steel_unit_purpose_validation_tolerance/v2_20260727`. It supersedes blanket
validation tolerances for the active Phase-2 path without changing solver
formulation, physical constraints, frozen inputs or governed results.

- cumulative production, deadlines, carried state and terminal state: 1 t;
- frozen prices and other immutable input identities: exact fingerprints;
- hourly money identities: EUR 0.01;
- trajectory/year cost reconciliation: `max(EUR 1, 1e-8 * scale)`;
- electricity and material balances: their small unit-specific tolerances;
- binary and structural identities: strict.

For the six registered per-trajectory electricity guardrails, the governed
tolerance remains exactly `1e-6 MWh_e`. Threshold comparison may additionally
recognise at most 256 binary64 ULPs at the comparison scale (never less than
one) as non-accumulating comparison roundoff. This allowance is separate from
the governed tolerance and from the solver feasibility tolerance; raw residual,
positive excess, ULP allowance and method remain explicit evidence. Unknown
threshold purposes fail closed, and an excess of `1e-9 MWh_e` remains a fail.

Acceptance tolerances do not accumulate. Validation-only relaxation is allowed
only for registered production/deadline/terminal constraint families and must
be bounded by the family tolerance. Unknown active families fail closed. The
executed-block `rolling_production_terminal_quota_equality` and explicit
in-horizon cumulative-deadline
`rolling_production_future_terminal_quota_equality` are the two literal
families in this exact-quota class; no name pattern is used, and physical
balances, capacities and economic rows remain outside this registration. The
C0 sale containment oracle works on an isolated clone, fixes the shared
incumbent at full precision and export at zero, records every active constraint
row, verifies the original-model fingerprint is unchanged, and rejects repeated
validation that accumulates components. Human-readable rounding is presentation
only and may not drive machine pass/fail evidence.

The active Phase-2 runner is policy-enforced. The fingerprinted inventory of
older S4/C5 runners is explicitly legacy-exempt; any new runner must import the
canonical contract or be deliberately reviewed into that inventory. This
decision does not authorize a governed Gurobi rerun or rewriting prior evidence.

The completed Phase-2 full-matrix source attempt remains immutable even when a
later policy corrects only its guardrail interpretation. A posthoc re-audit must
be no-solve, bind the source artifacts by hash, preserve the original failed
status, write a new identity-scoped local attempt, and describe supersession as
guardrail interpretation only. It cannot promote a candidate or create a new
physical, economic, market or held-out-data claim.

## Benchmark Decisions

### 5. Perfect foresight is oracle only

Perfect foresight is an upper-bound benchmark. It is not a realistic operating strategy and must never be described as one.

### 6. Price-insensitive benchmark is required

A price-insensitive benchmark remains mandatory.

Reason:

- the thesis question is not only whether the optimiser works;
- it is whether forecast/scenario-informed flexibility beats simpler non-price-responsive behaviour.

## Risk And Scenario Decisions

### 7. Scenario probabilities are required

Scenario files used by the optimiser must have explicit probabilities.

Reason:

- stochastic optimisation and CVaR interpretation depend on probability mass;
- missing probabilities are a methodological red flag, not a small formatting issue.

### 8. Validation-only selection

Model, scenario, and CVaR policy selection must be validation-based. Test-period evidence is for frozen-policy out-of-sample evaluation only.

This applies to:

- scenario configuration choice;
- selected-week policy use;
- future CVaR gamma selection.

### 9. CVaR exists, but is not yet the command-centre default

The repository already contains meaningful CVaR implementation work. However:

- CVaR is not the current command-centre default;
- the hardened default path remains risk-neutral selected-week hydrogen.

This distinction must be preserved in docs and reporting.

## Quarter-Hour And Truth-Type Decisions

### 10. Observed-vs-counterfactual quarter-hour distinction is mandatory

Quarter-hour work currently has two different truth regimes:

- observed-market quarter-hour evaluation;
- counterfactual / synthetic quarter-hour path support for downstream experiments.

These must remain explicitly separated.

Observed-market quarter-hour results must not be mixed with synthetic-path results as if they were the same evidence type.

## Current Transition

### 11. Deterministic response diagnostics pass with partial temporal and anchor coverage

The price-free rolling baseline, represented-material procurement ledger,
lexicographic fixed-reference cost objective, bounded sensitivities,
information-safe flat/synthetic price-series interface, cumulative
production-progress correction, bounded VN25 development response, governed
D-D+4 point-forecast integration and deterministic response diagnostics all
pass. The current decision is `price_response_valid_anchor_coverage_partial`.

This permits governed interpretation of the solved deterministic point-forecast
response using the governed source vintage, origin, delivery timestamp,
information-availability timestamp, market area, units, resolution and
missing-price policy. It does
not permit bidding, settlement, export revenue, ETS, stochasticity, CVaR or
mFRR. The fixed-reference physical baseline remains separately price-free, residual
electricity/NG remain excluded, and no endogenous route-economic claim is made.
The accepted VN25 response is only an upper-bound development sensitivity;
historical/unit-contract claims remain blocked by omitted VN25 operating
features, the unresolved IJ01 CHP split and the BF-pellet boundary recorded in
Decision 4K.

## Data And Cleanup Decisions

### 12. `data/01_cleaned/` is a separate policy stream

Tracked cleaned-data modifications must not be handled as routine untracked cleanup.

Reason:

- the tree mixes baseline inputs, generated derivatives, and diagnostics;
- cleanup requires a family-by-family policy decision first.

### 13. Important historical attempts must be summarised before cleanup

The repository contains noncanonical branches that still matter methodologically:

- May 2026 forecasting campaign;
- LEAR Strict / Lago work;
- quarter-hour phase workflow;
- scenario calibration / undercoverage audits;
- hydrogen support/readiness diagnostics;
- CVaR validation and anomaly work.

These should be summarised before any cleanup that would make their role harder to understand.
