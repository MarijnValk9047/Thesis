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

### 11A. Reachability-aware 1% terminal bands are the accepted DEVELOPMENT comparability contract

Phase-4 v1 and v2 froze the calm price-insensitive final carried-state vector
before responsive results, but overlaid exact or banded endpoint constraints on
the builders' existing cyclic horizon-end inventory equalities. Their governed
C0 infeasibilities therefore diagnose contradictory endpoint policies, not a
physically unreachable 1% band.

The corrected run
`steel_c5_phase4_reachability_aware_terminal_band_v3_20260727` keeps exact-zero
targets and an unsearched +/-1% band for nonzero targets. When the campaign
endpoint enters the D-D+4 look-ahead, the physical horizon ends at that
campaign endpoint, the relevant cyclic inventory equalities are replaced by
the frozen band, and cumulative BOF/EAF/HSM/DSP/import route bounds subtract
already executed route output. This prevents a replan from promising route
progress that its executed first day does not preserve.

Both frozen DEVELOPMENT periods pass all six rolling cases, 12 C0/C1
trajectories and 84/84 models. All nine carried-state families are inside the
common band, maximum terminal-band excess is zero, and physical/accounting and
non-anticipativity checks pass. The resulting represented-procurement cost
table is authorized only as
`development_common_terminal_band_1pct_cyclic_replacement_cost_comparison`.
It is not annual evidence, a held-out result, or an economic-uplift/promotion
claim. An inventory-value bridge is no longer required for this bounded Phase-4
comparison, but would still be needed to monetize residual within-band
inventory differences rather than treat the 1% corridor as operationally
equivalent.

### 11B. Phase 5C corrects the Badarinath behavioural metrics without fitting the model

The zero-solve run
`steel_c5_phase5c_source_mechanism_adjudication_v1_20260727` supersedes only
the interpretation of two historical directional checks. Badarinath's BF
discussion is about capacity-normalised efficiency/utilisation, not an
absolute BF6 > BF7 throughput ordering. Table C.6 correlates hourly changes in
storage level with price, not inventory level with price. The corrected DRI
metric is positive in both frozen no-export DEVELOPMENT weeks (0.289352 and
0.293885). Capacity-normalised BF6/BF7 loading is near parity, while the
asset-specific efficiency comparison remains not comparable because a public
separate-output/nameplate denominator is unavailable.

Athanasiadis confirms a negative-marginal-cost WAG-use term and a marginal cost
on accumulated CO2. These remain modelling precedents only. They do not define
an export contract, make the current emissions boundary ETS-ready, or override
the Phase 5B resource-capped physical result. No WAG credit, ETS cost, price
floor, physics or source-driven parameter is added.

The accepted no-export model is frozen. Phase 5C authorises frozen terminal-
aware held-out validation as the next separate gate. It does not authorise
export, bidding, settlement, ETS, stochasticity, CVaR or mFRR, and it does not
retroactively alter historical candidate selection or claim numerical
Badarinath replication.

### 11C. Phase 5D flexible-heat NG policy is retained as a superseded sensitivity

The governed DEVELOPMENT run
`steel_c5_phase5d_source_backed_ng_mechanism_closure_v1_20260727` reopens only
the separate user-authorized emulation layer. The strict source-driven model
and its endogenous flexible-heat allocation remain unchanged as a comparator.

No source-backed C0 plant-specific NG share exists for HSM, PEFA, boilers or
generators, so those candidates are rejected. The selected policy acts only
inside the already conserved 3.07-PJ-LHV/y flexible other-site heat service:
1.65 PJ-LHV/y is assigned to NG and the remaining 1.42 PJ-LHV/y to WAG. This is
a transparent Athanasiadis-aligned operating/calibration policy, not an
endogenously identified burner preference and not a change in total heat
demand, prices, physics, production targets, terminal bands or export
economics.

February passes before July is opened. All 28 rolling C0/C1 models and all
native validation checks pass. Full-site fixed NG remains 8.005 PJ-LHV/y,
core HSM/PEFA/boiler/generator NG remains zero, and total named C0 NG becomes
9.655 PJ-LHV/y versus the 9.666-PJ-LHV/y real-site anchor. HSM reheating, PEFA
malerij and PEFA branderij heat balances remain active and entirely WAG-
supplied. WAG-generator electricity improves in both DEVELOPMENT weeks without
export, and total WAG generation is effectively invariant.

The policy was initially promoted only within the user-authorized emulation
boundary. Phase 5E supersedes that promotion because 8.005 of its 9.655 PJ/y
C0 NG result remains an anonymous fixed component and violates the later
carrier-specific residual criterion. The run remains valid historical
DEVELOPMENT evidence, but the policy is sensitivity-only and nonpromoted.

### 11D. Phase 5E uses exact MER annual service partitions and keeps them outside dispatch

The official 2025 MER detail study is now the primary annual energy and Scope
1 contract where its configuration and boundary match. It gives complete,
independently stated C0/C1 NG, electricity, process-gas, generator and CO2
partitions. The old 9.666-PJ/y C0 NG comparison is superseded by 12.5 PJ/y;
the C1 gas-scenario primary is 46.7 PJ/y. Athanasiadis remains secondary and
Badarinath remains a directional-behaviour source.

`steel_c5_phase5e_source_backed_anchor_closure_v1_20260727` passes all 14
primary annual source-accounting comparisons, six carrier-specific coverage
gates and both generator balances. Named NG and CO2 coverage is 100% in C0/C1;
named electricity coverage is 83.2%/91.0%. The visible electricity boundary
remainders are derived from two independently stated MER totals and are not
model-residual plugs. Fuel-proportional WAG electricity is 2.519 TWh/y in C0
and 1.197 TWh/y in C1, within 0.34% and 2.67% of the secondary anchors.

The annual source services are fixed reporting partitions. They do not enter
dispatch, feasibility or represented procurement cost, and directly
overlapping endogenous quantities are not added again. The legacy 8.005-PJ
solver field is excluded from the Phase 5E full-site account. Coal is governed
on the official 120.8/58.0-PJ energy basis; the older 3.66-Mt mass definition
is not used to alter physical coal/coke inputs.

A fresh February no-export run passed before July opened. All 28 C0/C1 models
and 24 Phase 5E dynamic checks pass, including production, terminal, carrier,
steam, WAG heat-supply, 9.9-GJ-LHV/t DRI NG intensity, zero export and positive
DRI inventory-change/price direction. Phase 6 design is authorized. Phase 6
execution remains blocked until a separately frozen held-out dynamic run
passes. Bidding, settlement, ETS, stochasticity, CVaR and mFRR remain out of
scope.

### 11E. The HSM controller is active and HERACLES narrows but does not close the freeze blockers

The user-authorized HSM controller is the default development path. Each
24-hour block uses 55% COG/45% NG by volume in C0 and 20% COG/80% NG in C1,
with BFG and BOFG excluded. On the configured energy basis the NG shares are
62.384% and 89.021%. Explicit HSM NG displaces the C0 anonymous NG component
hour by hour. February passes before July opens and all 28 C0/C1 rolling models
pass. WAG production remains approximately 57.352 PJ/y; the released WAG is
shown as additional generator use or flare rather than used to correct WAG
production.

This remains a transparent development abstraction. The QRA supports the
design-flow volume shares, while the definitive 2025 HERACLES technical Part B
confirms only the direction that WBW2 needs more NG as COG availability falls.
Neither source establishes 24 hours as the real operating timescale.

The page-verifiable `C5_HERACLESS_BLOCKER_EVIDENCE_GATE.md` governs the document
finding. It resolves the 85% VN25/15% IJM-01 statement as operating time, not
output allocation. It supports separately reviewed tests for DRI/EAF
transition, bypass, maintenance and cold-DRI decoupling; validates separate
8.1/1.8-GJ-NG/t-DRI and 0.3-GJ-electricity/t-DRI evidence; and supports only
topology for DRI/EAF steam and the 83,400-m3 oxygas holder. All related
candidate-register rows are non-executable.

HERACLES does not supply a VN25 minimum-fuel rate, full carrier-specific WAG
source-to-sink allocation, usable oxygas-store energy, complete steam balance,
BF6/BF7 denominator, real HSM mixture timescale or held-out result. The 54-PJ/y
WAG value remains annual context and may not be used to fit WAG yields. Model
freeze and Phase 6 execution therefore remain blocked by the separately frozen
terminal-aware held-out dynamic validation. Any source-backed operating-state,
steam, generator or storage change requires its own reviewed implementation
gate.

### 11F. Phase 5G baseload integration fails closed before deterministic freeze

Phase 5G implements a one-to-one source-service overlap contract and constant,
configuration-specific site electricity and NG loads selected with one shared
10-percentage-point share per carrier. The electricity baseload enters gross
demand before the existing no-export balance. The NG baseload is NG-only,
constant, non-displaceable, priced once through named procurement and reported
with a separate first-order combustion-CO2 proxy that is not ETS-ready Scope 1.
The Phase 5D fixed/flexible bridge is inactive; the Phase 5F HSM controller is
unchanged.

The explicit baseline and selected-validation stages each solve 56/56 rolling
models. All 194 physical checks and all eight HERACLES validations pass. The
selection procedure chooses 90% electricity and 90% NG. Both electricity
anchors and C1 NG improve, but C0 NG worsens from 64.00% to 90.33% error:
the electricity baseload induces about 12.1542 PJ/y of generator NG, which is
additional to the 7.1998-PJ/y C0 NG baseload. This is a coupled physical
response, not duplicate accounting.

The required both-configurations improvement rule therefore fails. Decision is
`baseload_selection_gate_failed_model_not_frozen`; the attempted rows are
`selected_validation_failed_not_promoted`. The governed runner stops before
held-out evaluation and Phase 6 is not authorised. A prior local orchestration
attempt opened the old held-out scratch cases before the gate-order defect was
corrected. Those results are excluded, no reselection used them, and they may
not support a pristine held-out claim.

Any continuation requires a separately authorised revision that evaluates
electricity and NG shares jointly on validation and then uses newly frozen,
previously unseen held-out periods. The current result does not authorise exact
anchor filling, configuration-specific shares, a model freeze, DA bidding,
settlement, stochasticity, CVaR or mFRR.

### 11G. Phase 5H fails closed because the residual-steam maximum is not public

Athanasiadis Figure 38 establishes four aggregate residual modelling terms:
electricity, natural gas, steam and direct CO2. Its steam equation establishes
a constant residual term in addition to operational plant demand. This is
accepted as topology and modelling-structure evidence, not as a Tata-specific
numerical input.

The required normal-operation steam maximum is absent. The source does not
provide steam pressure or enthalpy, annual operation, condensate treatment or
overlap with the current explicit 15-bar demand. HERACLES approximately 50 t/h
is startup-only. Boiler nameplate times 8760, steam spill and the retired 9-PJ
value may not be reinterpreted as demand. The steam branch consequently stops
without a solve and no validated four-residual contract can exist.

The builder may retain zero-default residual-steam and reporting-only residual-
direct-CO2 interfaces for a future sourced gate. The CO2 term is excluded from
physical constraints, cost and ETS. The permitted electricity/NG/CO2 campaign
is diagnostic only and rejects actual generator or boiler NG above its mapped
MER component before algebraic NG and CO2 screening. Four fresh held-out
periods are frozen but remain unopened because selected-contract validation is
unreachable after the steam failure.

The permitted diagnostic branch completes 560/560 models. Ten-percent
electricity is the only candidate that does not enlarge a source-component NG
exceedance. It reduces C0 flare by about 1.387 PJ/y but leaves electricity
errors at 38.97%/28.06%. At 20% and above, C0 generator NG exceeds the MER
1.9-PJ/y component. Conditional 90% NG and 90% direct-CO2 shares would reduce
NG errors to 6.39%/2.68% and CO2 errors to 1.44%/1.60%, but add about EUR
109.8/180.4 million/y of NG cost and remain aggregate validation abstractions.
They are not promoted.

Decision is `four_residual_gate_failed_residual_layer_not_promoted`. No
residual share is executable, the process/HSM model remains active, the
deterministic model is not frozen, and Phase 6 execution remains blocked. A new
calibration search requires a new source or explicit methodological decision.

### 11H. Phase 5I freezes the represented boundary with electricity only

The user-authorised Phase-5I decision promotes only the Phase-5H
source-compatible 10% electricity candidate. Exact constant loads are
15.707829645182 MWh/h in C0 and 17.538616398437 MWh/h in C1. They are classified
as `validation_selected_user_authorized_aggregate_electricity_baseload_abstraction`:
not observed hourly demand, Tata-approved allocation or price-responsive
flexibility. Residual NG, steam and direct CO2 remain zero; Phase-5D bridges and
failed Phase-5G rows remain inactive.

The four newly frozen periods open once without reselection. All 56 C0/C1
rolling models, native physical/terminal checks and source-component overlap
checks pass. C0 generator NG remains 0.109457 PJ/y against the 1.9-PJ/y MER
component. The decision is
`represented_boundary_deterministic_model_frozen_for_phase6`.

This freezes the physically and terminally validated represented boundary. It
does not claim a full-site digital twin, exact annual anchor replication or
ETS-ready emissions. Annual NG, steam and CO2 gaps remain outside dispatch and
cost.

### 11I. Phase 6A validates deterministic DA quantity bidding and settlement

The executable Phase-6A bid is the frozen point-forecast schedule's net grid
purchase, submitted as a price-taking quantity using forecast-origin
information only. Full acceptance and zero deterministic imbalance are explicit
accounting abstractions; settlement uses realised prices. The electricity
baseload remains fixed net demand. Export, bid-price curves, imbalance-market
pricing, stochasticity, CVaR, mFRR, ETS and product revenue are absent.

The price-insensitive benchmark uses a flat EUR 80/MWh physical schedule. The
perfect-foresight case is isolated and marked `not_submitted_counterfactual`.
All 168 evaluated rolling models, 408 physical checks and 13 timing/accounting
checks pass. Point-forecast operation improves represented four-period cost
against the flat reference by about EUR 0.051 million in C0 and EUR 3.208
million in C1. Oracle regret is about EUR 0.032 million and EUR 0.373 million.

Three `y_true` gaps on 13 July 2025 are filled only for settlement and the
oracle from a fingerprinted Fraunhofer ISE Energy-Charts series. The remaining
21 prices for that day match the governed source exactly. The original forecast
parquet and executable information set remain unchanged.

Decision is `phase6a_deterministic_da_bidding_and_settlement_validated`.
Phase-6B scenario-contract design is authorised, but scenario execution awaits
explicit probabilities, non-anticipativity and an expected-value benchmark;
CVaR follows only after those pass.

### 11J. Phase 5J reopens the freeze after correcting generator-NG costing

Phase 5J corrects a narrow activation defect: C0 aggregate-generator NG cost
was conditional on the retired full-site NG bridge instead of on the aggregate
generator itself. The correction leaves the legacy fixed/flexible bridge flows
inactive while pricing physically active generator NG. Production physics,
capacities, WAG yields, HSM policy, steam, storage, zero export and terminal
rules are unchanged.

The former rejection of 20--90% electricity shares is consequently invalid.
With corrected cost accounting, the shared 90% candidate gives validation
electricity-anchor errors of 10.05% in C0 and 3.20% in C1, C0 generator NG of
zero and C0 flare of 0.542 PJ/y. A 5% uniform WAG-yield reduction is not
promoted because it only reduces flare to 0.468 PJ/y while increasing grid
purchase.

All 56 fresh held-out models and native physical checks pass, but C0 flare is
1.059 PJ/y and exceeds the predeclared 1.0-PJ/y robustness limit. The limit is
not relaxed and no held-out retuning occurs. Decision is
`phase5j_heldout_gate_failed_previous_freeze_reopened`: the Phase-5I freeze is
superseded, Phase 6A is retained as historical accounting/timing evidence on
the former boundary, and Phase 6B is blocked. Any next attempt requires a new
source or methodological decision for carrier-specific buffering or gas-holder
operation; another baseload or WAG-yield calibration search is unauthorised.

### 11K. Phase 5K freezes a user-authorized represented boundary

Phase 5K is a deliberate methodological override of the Phase-5J stop. The
carrier-level source audit finds no unit or activity-basis defect and shows that
the C0 WAG excess is concentrated in COG. A source-identified coefficient fix
is therefore unavailable. The user-authorized final development boundary uses
a C0-only 0.95 WAG-yield multiplier and leaves C1 yields unchanged.

The same frozen contract promotes the shared 90% electricity baseload, a
constant 7 PJ/y site NG service in C0 and C1, zero residual steam and a common
2.0 MtCO2/y aggregate direct-emissions term selected on validation from a
0.5-Mt grid. Electricity and NG are fixed, inelastic and included in physical
procurement and cost exactly once. The NG term is not WAG-displaceable. The CO2
term is reporting-only, excluded from dispatch, objective and ETS, and kept
separate from recalculated WAG and NG combustion emissions.

All 56 validation and 56 newly frozen held-out models pass without held-out
reselection. Decision is
`user_authorized_represented_boundary_deterministic_model_frozen_for_phase6`.
This freezes only a physically and terminally validated represented boundary;
it is not a complete Tata-site allocation, exact annual backtest, digital twin
or ETS-ready emissions account.

### 11L. Phase 6A passes on the Phase-5K frozen boundary

The deterministic DA quantity-bid and realised-price settlement layer is rerun
on the exact Phase-5K fingerprints. The point-forecast case uses only
forecast-origin information; realised prices enter settlement only. The flat
price-insensitive comparator and ex-post perfect-foresight oracle remain
mandatory and isolated.

All 168 evaluated models and all physical, timing, bid and settlement checks
pass. Decision is
`phase6a_phase5k_deterministic_da_bidding_and_settlement_validated`.
Phase-6B scenario-contract design is authorized, but stochastic execution is
not: explicit probabilities, non-anticipativity and an expected-value benchmark
must pass before CVaR, and mFRR remains later.

### 11M. Strict LEAR hourly/QH D--D+4 inputs are frozen on common observed support

The unchanged `lear_lago_direct_dplus4_strict_no_future_1092` hourly anchor is
paired with the causal `qh-fs1__mean_shape__hourly_anchor__lear_strict` model.
The canonical full run `20260729_strict_lear_dplus4_full_a03` exports coupled
hourly and QH point forecasts and nested probability-weighted 30/10 scenario
sets for 116 common evaluation origins covering delivery days 18 March through
19 July 2026.

All hard timing, probability, nesting, uniqueness, native-DST and hourly/QH
mean-parity checks pass. Eight post-spring-DST origins are excluded because the
frozen Strict LEAR definition requires complete 24-hour lag vectors; five July
origins are excluded because D--D+4 intersects the genuinely unobserved 24 July
day. No synthetic lag hour or evaluation-price interpolation is introduced.

The QH mean shape improves MAE by 2.30% against flat hourly repetition on
common support, with a paired DM p-value of approximately `8.54e-40`.
Validation selects level scale 1.00 and shape scale 0.75. Evaluation p05--p95
coverage is below 85% for both 30- and 10-scenario exports; therefore the
artifacts are frozen as optimization inputs, while calibrated-risk-coverage
claims remain prohibited. The 30-set is primary and the nested 10-set is the
computational sensitivity. Hydrogen, perfect foresight, and steel optimization
remain separate later evaluations and must reuse these artifacts without
forecast retuning.

### 11N. Phase 6B hourly stochastic steel DA engineering gate passes

The accepted Phase-6B runner adds only an hourly risk-neutral Strict LEAR
D--D+4 point/S10 price--quantity bid, realised D clearing, exact physical
redispatch and rolling state handoff around the frozen Phase-5K C0/C1 boundary.
The sixteen-tier grid, scenario probabilities, physics, route bands, quota,
terminal rules, settlement and represented cost scope are common across
H-point, H-S10, price-insensitive and configuration-matched true PF.

Only D is executed and settled. Actual prices remain outside non-oracle
bidding inputs. All finite inventories, cumulative production and cumulative
BOF/EAF/HSM/DSP/imported-slab progress are carried. A common week-end inventory
band is selected once from a flat EUR 80/MWh price-insensitive run before
responsive strategies, and the existing campaign-endpoint truncation and
cyclic-replacement policy is preserved.

Run `steel_phase6b_hourly_da_bid_clear_redispatch_a03_20260730` passes 256/256
checks and all 156 solves are optimal. A03 is exactly cost- and production-
identical to a02 and supersedes it only by adding `fixture_id` to every
consolidated bid, clearing, redispatch and scenario-audit key. Decision is
`hourly_stochastic_DA_bid_clear_redispatch_validated_on_engineering_fixtures`.

The day/week amounts are engineering evidence only. They do not authorize a
long-run economic claim, QH steel execution, scenario retuning, CVaR, mFRR,
export, ETS or product revenue. Scenario undercoverage remains a mandatory
warning. Phase 6A remains the historical quantity-only bridge and is not a
matched price--quantity clearing result.

### 11O. Phase 6C validates quarter-hour steel DA execution on the matched week

Phase 6C makes the shared Phase-5K/6B physical and market engine explicitly
granularity-aware. Interval quantities use `dt = 0.25`; 120/24 physical hours
become 480/96 intervals, hourly rate bounds are scaled once, daily commitment
remains daily, and fixed historical hour calendars fail at QH resolution. The
accepted hourly `dt = 1` normal-day results are reproduced with maximum cost
error below EUR `2e-9` and zero production error.

The governed run
`steel_phase6c_qh_da_bid_clear_redispatch_a01_20260730` executes QH-point,
QH-S10, price-insensitive and configuration-matched true PF for C0/C1 over
27 April--3 May 2026. It reuses the accepted hourly terminal bands and frozen
QH artifact `20260729_strict_lear_dplus4_full_a03`; no forecast training,
tuning or QH terminal target selection occurs. All 112 bidding/redispatch model
builds and every lexicographic solve terminate optimally. All 203 checks pass,
including 86,016 bid rows, 5,376 realised intervals, 56 exact state handoffs,
hourly/QH scenario-anchor identity, settlement, zero export, terminal bands,
production and PF dominance. Every trajectory ends at 168 hours, 672 intervals
and 129,452.05479452055 t within numerical tolerance.

Decision is `qh_da_bid_clear_redispatch_validated_on_bounded_common_week`.
Headline hourly/QH differences remain a combined granularity effect, not an
identified forecast-shape value. Results are not annualised and do not support
a profit or long-run economic claim. QH-S10 p05--p95 coverage is only 74.27%.
Without plant-specific QH ramp/start/minimum-load/outage/CHP evidence, QH
physical flexibility is an upper-bound development result. CVaR, mFRR, ETS,
export, product revenue and imbalance remain outside scope.

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

### 14. Hydrogen horizon/granularity comparison is isolated from model selection

The 307-day hourly D-only model-family experiment remains frozen evidence for
selecting Strict LEAR. The new hydrogen experiment is a separate common-support
evaluation of `H-D`, `H-D4`, and `QH-D4`; it may extend support for the frozen
D-only specification but must not reopen feature, window, hyperparameter,
fallback, risk, physical, quota, bid, or settlement selection.

The operational comparison uses independent 11-day and 105-day episodes, true
daily receding-horizon execution, support-prorated hard weekly quotas, a
primary 30-path set, and a nested 10-path runtime sensitivity. Only delivery
day D is cleared and settled. Configuration-matched true perfect foresight and
price-insensitive behaviour are mandatory. Scenario undercoverage remains a
binding reporting warning and prohibits calibrated-risk claims.

Canonical method record:
`docs/optimisation/STRICT_LEAR_HYDROGEN_HORIZON_GRANULARITY_COMPARISON.md`.

Accepted run `20260729_strict_lear_horizon_granularity_full_a01` passes all
headline gates. With 30 scenarios, observed horizon value is EUR +82,835 over
105 days, but its seven-day block-bootstrap interval includes zero. Observed
QH granularity value is EUR -1,727,401 and its interval remains negative. The
QH result is retained without evaluation tuning: it combines much higher
emergency import with the already documented scenario undercoverage. The
nested 10-set materially reduces runtime but is not economically equivalent
to 30 in this test. No general claim that QH granularity has negative value is
permitted outside the frozen plant, policy, support, and scenario design.

Seven primary `QH-D4` stochastic-30 bidding solves reached the initial
300-second limit. The complete policy was rerun uniformly at 900 seconds with
all model/data settings and the 0.001 MIP-gap frozen; all bidding and
redispatch solves then terminated optimally. This convergence repair is part
of the accepted lineage and must be disclosed with runtime comparisons.
## Performance decision -- optimized-equivalent rolling solves (2026-07-30)

- Hydrogen canonical rolling runners and the active deterministic steel runner
  default to `performance_mode: optimized_equivalent`.
- `legacy_rebuild` is diagnostic only and remains required for parity tests.
- Cache hits refer to immutable inputs and structural metadata; both model
  families still report `pyomo_model_rebuilt = true` until persistent reuse is
  separately proven.
- Hydrogen may use executed-D lazy extraction because full-horizon scenario
  economics are computed directly from the unchanged solved model. Audit mode
  retains full future-path extraction.
- Scenario-dependent hydrogen warm starts require exact scenario ID and
  residual-block identity. Steel cross-replan warm starts remain a documented
  cold fallback pending a formally validated mapper.
- July-30 diagnostics passed all ledger and objective parity gates. The QH
  speed targets were not met, so no 2x/1.5x claim is permitted; solver time is
  the remaining bottleneck. See `OPTIMISATION_PERFORMANCE_CONTRACT.md`.

## Representative D-only quarter-hour study decision (2026-07-31)

The thesis market-value study is frozen as a four-regime, D-only,
risk-neutral S10 counterfactual comparison. The three forecast families are
audited fairly with identical origins, information cutoffs, validation-only
calibration, residual pools, scenario construction and probability contracts,
but Strict LEAR remains the ex-ante main model. Failure of a hard Strict timing,
data or scenario check stops the study; it does not authorize fallback to FS3
or XGBoost or selection on the four economic weeks.

The QH transformation is additive and mean preserving. Statistical validation
uses all true held-out QH observations, including the -499.62 EUR/MWh extreme.
The separate observed H2 economic illustration is frozen to 18--24 May 2026,
the complete non-extreme week with smallest robust distance to the complete-week
median. The counterfactual H2 bridge uses the typical-winter case. H2 remains a
mechanism check only and receives no horizon or scenario-count sweep.

The steel arms are A hourly Strict S10, B QH with each hourly path repeated
four times, and C QH with the mean-preserving scenario shape. They share one
internal QH physical model, start conditions, quota/state contracts and
counterfactual realisation. Price-insensitive and true-PF benchmarks are
mandatory. Reported realised differences use `C_A-C_B`, `C_B-C_C` and
`C_A-C_C`, with positive meaning a saving. A negative or reversed effect is a
valid finding and may not be hidden or treated as a technical failure.

The frozen regime weeks are 4--10 November 2024 (high volatility), 2--8
December 2024 (typical winter), 13--19 January 2025 (high prices) and 14--20
July 2025 (typical summer). They are representative cases only. QH prices in
those weeks are synthetic counterfactual paths, not historical observations;
no annualisation or annual savings claim is allowed. C1 is explicitly
conditioned on maintenance-free normal operation, with both weekly EAF
maintenance and the annual outage disabled.

Steel horizon and scenario-count sensitivities are one-factor-at-a-time Arm-C
diagnostics. S30 is nested from the same raw draw and S30 reduction used for
S10. Horizons above 24 hours fail closed until causal Strict D+1--D+4 support
exists; stitching forecasts from future D-only origins would leak information
and is forbidden. A solver time limit is reported as runtime-quality evidence
and does not by itself reopen physical bounds. mFRR remains interface-ready but
inactive; CVaR, ETS, export, product revenue, emergency import in steel and
imbalance optimisation are excluded.

Accepted implementation/input lineages are
`20260731_donly_family_audit_s10_s30_v3`,
`20260731_four_regime_inputs_s10_s30_v11`, and the representative
steel/H2 executors. `20260731_h2_mechanism_s10_v3` is accepted diagnostic
mechanism evidence. `20260731_c0_winter_abc_validation_v2` proves the executor
for one C0 regime only and predates the resolved physical blocker. The original
C1 24-hour physical model remains infeasible; no bound was widened.

The authorized replacement is `24e48p`: 24 hours of D-only price/scenario
information and execution inside a 48-hour physical plan. The second day has
no price, bid, clearing, execution or settlement and is only a physical
continuation witness. Run `20260731_split_horizon_24e48p_gate_v5` passes 6/6
C0/C1 hourly/QH and C1 S10 trajectories, 60/60 checks and all bid, objective,
settlement, physical and state-handoff reconstructions. Flat-price parity is
defined as exact production plus expected-objective parity inside the frozen
0.1% MIP gap; aggregate carrier timing remains diagnostic because hourly and
QH clearing impose different within-hour constraints. The unnecessary final
canonical-bid MIP re-solve is removed; the feasible bid incumbent from the last
proven physical tier is retained and independently reconstructs clearing.

The v11 manifest has 80 executable D-only/S10/S30 rows and 32 blocked true
D+1--D+4 price-horizon rows. This split horizon does not create causal future
prices and does not authorize stitched future D-only forecasts. Central
four-week economics and the S30 sensitivity may proceed; price-horizon
sensitivities remain blocked.

## Representative-study planning-incumbent decision (2026-08-01)

For the four-week representative D-only quarter-hour steel study, planning mode
`expected_cost_incumbent` (V1) is promoted for every A/B/C arm, C0/C1 case and
the central S10 and steel-only sensitivity paths that use the representative
runner. Planning still proves the minimum cumulative production-progress
deviation first and the minimum expected represented cost second. It then keeps
that feasible incumbent and does not perform the third planning physical
tie-break solve. This is a selection of a different incumbent within the same
preserved production and expected-cost optima, not an approximation of a worse
cost optimum.

The promotion is based on the frozen runtime audit: median planning time falls
from 437.7 to 180.0 seconds (60.6%), median complete-day time is about 191
seconds versus about 467 seconds, all physical checks pass, the expected-cost
optimum is unchanged and V1 reproduces across three independent processes. The
observed realised one-day difference of EUR 1,288.83 (about 0.014%) is accepted
as economically immaterial for the intended million-euro research effects, but
must remain visible. Inventory, flaring, commitments, bids and rolling handoff
can differ because not all internal quantities are priced.
This project-level decision supersedes the audit's earlier retain-V0
recommendation without rewriting that historical diagnostic output.

The full planning physical tie-break (V0) remains selectable as an audit
reference and remains the default of the general Phase-6D diagnostic config.
Redispatch retains its production, represented-cost and physical-tie-break
hierarchy. All material, WAG, NG, steam, terminal and handoff checks and the
900-second solver cap remain mandatory. Representative run configs, manifests,
summaries and registry lineage record V1, the skipped planning tie-break, both
planning optima, Gurobi version, seed 0, MIP gap 0.001 and integer
feasibility tolerance `1e-9`. A/B/C claims remain realised-cost differences;
planning-incumbent sensitivity is a disclosed limitation and exact V0 path or
bid parity is no longer a promotion gate.

## Pre-matrix behavioural-validation decision (2026-08-01)

The four-week representative matrix is blocked by the governed diagnostic run
`20260801_pre_matrix_behavioural_gate_v1`. Before any solve, that run froze four
non-final shadow days: 2 March 2025 (typical/calm), 10 May 2025 (high
volatility), 8 June 2025 (negative/low) and 9 September 2025 (high price). All
have complete Strict S10, hourly actual, mean-preserving QH-overlay and
DST-aware previous-week-naive support, are mutually separated by at least 28
days and remain at least 28 days from every final regime week.

The seven pre-existing Phase-0 gates were reused without new solves and pass.
In the synthetic gate, S0 C0 completes and all 37 physical checks pass. S0 C1
also solves its production-progress and expected-cost planning tiers optimally;
the EUR 9,689,932.602 expected objective reconstructs exactly and maximum bid
reconstruction error is `3.1e-7` MWh. Actual-price intervalwise bid clearing
then produces no feasible complete physical redispatch path. The cleared path
contains one interval outside the ten planned scenario-import envelopes and is
49.812 MWh RMSE from the nearest complete planned scenario path. This is a hard
`actual_price_bid_clearing_to_physical_redispatch` failure, not a positive-
effect test or a solver time-limit result.

The run therefore stops fail-closed with decision `BLOCK` after one completed
and one infeasible trajectory. The other seven synthetic cases, all thirteen
shadow cases and all four final weeks remain unsolved. No source-directional
economic conclusion is available, no source calibration was performed and no
positive economic outcome was required. Emergency import, imbalance handling,
physical-bound relaxation and alteration of the frozen actual/scenario paths
remain unauthorized.

The next admissible task is a separate methodological resolution of how
out-of-sample intervalwise cleared quantities retain complete physical recourse
feasibility. It must preserve information timing, physical bounds, the frozen
bid/scenario contract and independent settlement reconstruction. The complete
behavioural gate must then be rerun and pass before the four-week central matrix
or S30 sensitivity may start. For the normal one-day `24e48p` contract, physical
hour 48 is a non-terminal continuation endpoint; reference-band distance is a
diagnostic and must not be misreported as an active terminal constraint.

## Canonical-bid repair and remaining shadow-recourse decision (2026-08-01)

The S0 C1 failure in `20260801_pre_matrix_behavioural_gate_v1` was a local bid-
step canonicalisation contract error exposed by price-support undercoverage.
The stochastic plan and expected-cost optimum were feasible, but an arbitrary
sample-equivalent bid-tier allocation rejected required volume at an unseen
actual price. Phase 6D now analytically applies the already frozen
`minimum_total_volume_then_highest_willingness_price` ordering. It performs no
additional solve and changes neither scenario dispatch, probabilities,
production nor expected cost. Diagnostic run
`20260801_s0_c1_recourse_diagnostics_v3` proves exact clearing feasible with
zero minimum recourse deviation; the pre-fix deviation was 5.275533 MWh.

The full repeated synthetic gate
`20260801_pre_matrix_behavioural_gate_v2_canonical_bid` passes 9/9 trajectories
with no infeasibility or solver time limit. Price-insensitive planning remains
the mandatory flat EUR 80/MWh benchmark. For the nested expected-objective
check only, its frozen dispatch is revalued on the same S10 prices without
replanning; directly comparing a flat-80 objective with an S10 objective is
forbidden. Administrative `episode_id` is likewise excluded from the physical
initial-state identity. C0/C1 responsive common-S10 objectives are respectively
EUR 122,801.70 and EUR 169,082.45 below the frozen price-insensitive schedules;
PF is EUR 44,371.65 below forecast execution. No positive final-week economic
effect is made an acceptance condition.

The conditional shadow gate passes seven cases and then blocks on the non-final
2 March 2025 typical/calm C1 case. The cleared path remains inside all ten
scenario quantity envelopes but is not a feasible complete physical path.
`20260801_shadow_typical_calm_c1_path_splicing_v1` classifies this as structural
path splicing: exact and numerically envelope-clipped clearing are infeasible,
the nearest complete scenario is feasible, and minimum recourse is 4.787437
MWh in one quarter. Two actual prices are outside S10 price support, but S30 is
not a proof of complete recourse and was not rerun for this diagnosis.

Decision: `BLOCK` remains active before any final regime-week solve. Selecting
robust/path-feasible bid coupling, explicit imbalance/bounded recourse, or a
scenario-complete execution convention changes the methodology and requires
explicit user authorization. Physical bounds, yields, quotas, settlement,
emergency import and scenario paths may not be altered implicitly. After the
selected method is implemented, the entire shadow gate must pass before the
four-week central matrix or scenario sensitivity can start.

## Explicit EUR 5,000/MWh execution-recourse decision (2026-08-01)

The user authorizes the explicit imbalance/bounded-recourse option. Physical
net import may deviate from the DA-cleared E-program through symmetric
non-negative upward- and downward-consumption deviation variables. The
redispatch objective charges their absolute energy at EUR 5,000/MWh. DA
pay-as-cleared settlement remains based exclusively on cleared energy; the
recourse penalty, absolute deviation, direction and affected intervals are
reported separately. E-program compliance may be claimed only for trajectories
with zero deviation.

The EUR 5,000/MWh value is an artificial prohibitive modelling penalty, not an
empirical imbalance-price claim. It is the only authorised penalty; no
imbalance-penalty sensitivity is retained. No emergency import, physical-bound relaxation,
realised-price alteration or scenario alteration is authorized. The full
synthetic and shadow behavioural gate must be rerun and pass before the four
final maintenance-free representative weeks start.

## EUR 5,000/MWh recourse gate result (2026-08-01)

`20260801_pre_matrix_behavioural_gate_v3_penalised_recourse` passes 22/22
trajectories: 9/9 synthetic and 13/13 shadow. No trajectory is infeasible and
no hard physical, economic or runtime gate fails. Material recourse occurs in
three C1 cases: 0.608812 MWh in the synthetic negative-price stresscase,
0.060734 MWh in the shadow negative/low-price case and 10.683906 MWh in the
former typical/calm blocker. Their penalties are respectively EUR 3,044.06,
EUR 303.67 and EUR 53,419.53. Those trajectories are explicitly not
E-program compliant.

Because 10.683906 MWh exceeds the previously proven lexicographic minimum of
4.787437 MWh, EUR 5,000/MWh is not treated as proof of minimum physical
recourse. The formerly stated four-week authorization is superseded. Positive
recourse requires the conditional minimum-imbalance gate and is never an
accepted economic result, irrespective of its EUR-5,000 charge.

## Controlled stop of first four-week central campaign (2026-08-01)

`20260801_four_week_central_s10_penalised_recourse_v1` is classified as
incomplete diagnostic evidence and not a thesis result. Fourteen of 56 selected
experiments completed, one high-prices B-QH-flat C1 experiment stopped after
two completed days, and no full A/B/C C1 comparison or four-week matrix exists.
The completed high-prices A-hourly C1 week uses 248.503443 MWh recourse (EUR
1,242,517.21) and the C-QH-shape C1 week uses 283.258327 MWh (EUR 1,416,291.63).
The B-QH-flat C1 third rolling day did not checkpoint during more than 75
minutes of observation. C0 central arms completed so far remain zero-recourse.

Decision: do not resume the remaining central selection. First diagnose the
rolling state-dependent C1 minimum imbalance and expose per-tier progress/runtime so
that an acceptable restart scope can be chosen. The one-day behavioural gate
remains valid for its bounded cases but is insufficient evidence for multi-day
rolling runtime and recourse quality.

## Conditional minimum-imbalance gate blocks the four-week run (2026-08-01)

The previous central runner continued after its documented manual stop because
`manual_stop_summary.json` was not executable control. PID 28756 was verified
as the exact Python 3.14 representative runner for
`20260801_four_week_central_s10_penalised_recourse_v1`, with the matching
20:24:18 start time, active CPU and recent checkpoint writes, and was terminated
at 23:25:16 local time. The preserved output is explicitly non-thesis-usable,
non-resumable and superseded by the conditional minimum-imbalance gate.

Decision: EUR 5,000/MWh is the sole imbalance penalty. Redispatch preserves
production progress first and then minimizes operational cost plus exactly one
penalty term. DA settlement remains a separate reconstruction on the cleared
E-program. If that economic solution has numerical zero imbalance, no minimum
solve is run and the physical tie-break follows. If it uses positive imbalance,
exactly one solve minimizes `sum(d_plus + d_minus)` with unchanged physics,
state, E-program and production optimum. A zero minimum hard-fixes both
deviation variables, reruns economics and then permits the tie-break. A positive
minimum is `emergency_recourse`, is excluded from A/B/C economics and stops all
remaining days and experiments. Unproven optimality and reconstruction failure
also stop fail closed.

The implementation adds an enforced `resume_authorized` run-control sentinel
and atomically flushed start/finish records for each solver tier. The old run
cannot be resumed, `--all-central-ready` is blocked, and the representative
runner is capped at one C1 week and three central A/B/C S10 D-only arms pending
new authorization.

Run `20260801_conditional_minimum_imbalance_gate_targeted_v1` proves the gate.
The synthetic `S0_C1_responsive` case returns exactly zero imbalance and skips
the minimum solve. All clearing, settlement, penalty, state-handoff and physical
identity checks pass. The 2-March-2025 typical/calm C1 case economically chooses
10.683906 MWh downward-consumption imbalance; the conditional optimal solve
proves that 4.787437 MWh remains physically unavoidable over two intervals
(maximum 2.562389 MWh), equivalent to EUR 23,937.18 at the fixed penalty. The
case is `emergency_recourse`, and both A/B/C eligibility and rolling continuation
are false.

Decision: `blocked_before_four_week_run`. The 15-January checkpoint-seeded
high-price diagnostic and the one-week trial are not started because the earlier
case triggered the mandatory stop. No remaining week, S30, horizon, penalty,
H2, mFRR or CVaR sensitivity is authorized. Further work requires a new user
decision on the structural/path-feasibility blocker; physical bounds, yields,
maintenance and terminal contracts remain frozen.

## Validation-derived path-feasibility repair is bounded by runtime (2026-08-02)

Decision: validation shadow actuals may be reduced to probability-free clearing
patterns consisting only of canonical accepted bid-step ranks by lead position.
Raw shadow prices are not transported to another origin. A pattern has no
probability, no expected-cost weight and no forecast-metric role. Its physical
recourse block clones the frozen state, physics, quota and terminal contract and
uses the same submitted bid variables as the ten unchanged economic S10 blocks.
The exact identity is physical import equal to the mask-cleared shared bid
volume. Constraint generation adds at most one deterministic worst violation
per round and stops after at most three rounds or any unproven solve.

Diagnostic run `20260802_path_feasibility_blocker_phase_b_v1` reproduces the
known 2-March-2025 minimum of 4.787436618 MWh. Adding one validation-derived QH
pattern grows planning by 9,038 variables, 204 binaries and 9,570 constraints.
The repaired plan and redispatch are proven optimal; realised imbalance is
exactly zero and the conditional minimum-imbalance tier is not invoked. The ten
S10 ids, prices and probabilities retain the same contract hash, feasibility
expected-cost contribution is zero and all physical, settlement and penalty
reconstructions pass. The longest repair tier is the feasibility-aware
canonical bid tie-break at 525.914 s, below the 900-s cap.

The mandatory full behavioural run
`20260802_path_feasibility_behavioural_phase_c_v2` is fail-closed before
augmentation of its first C1 case. After `S0_C0_responsive` passes, the normal
`S0_C1_responsive` expected-cost tier reaches `aborted/maxTimeLimit` after
906.454 s with 91,916 variables, 2,040 binaries and 95,681 constraints. It has
no proven optimum, so no pattern is added and the remaining 20 cases are not
started. The pre-solve `v1` attempt contains zero solver events and is retained
as non-resumable diagnostic evidence of a duplicate pattern-id check corrected
by deterministic exact deduplication.

Decision: `blocked_before_final_weeks`. Phase B establishes a valid bounded
structural repair, but Phase C does not meet 9/9 synthetic plus 13/13 shadow
PASS. No final week, four-week matrix or excluded sensitivity is authorized.

## Reduced feasibility canonicalisation is promoted; full gate remains pending (2026-08-02)

Decision: preserve the ten economic S10 paths and their expected-cost objective,
but replace the expensive full feasibility-aware canonical bid MILP. Exact
acceptance-signature symmetry breaking retains only the highest price step per
distinct non-empty clearing signature. During augmented secondary
canonicalisation, fix the 2,040 economic-scenario binaries at their proven
expected-cost incumbent and leave only feasibility-block binaries free. Fill
unused bid steps with zero only after exact economic- and feasibility-clearing
reconstruction. The raw incumbent without this reduced selection is rejected
because it permits avoidable economic redispatch imbalance even though a later
minimum solve can find zero.

The accepted method reproduces the repaired 2-March case in three independent
processes with identical S10, bid, scenario-dispatch, clearing, physical-
dispatch and next-state hashes. Complete augmented planning is 152.283--163.684
seconds and the reduced tier is 34.055--37.396 seconds, versus 416--526 seconds
for the old full canonical tier. The realised imbalance is exactly zero and the
conditional minimum-imbalance solve is skipped. `MIPFocus=1` is the sole added
performance option: it closes the former `S0_C1_responsive` blocker in 249.603
seconds for expected cost and 255.535 seconds including production progress.
Seed 0, gap 0.001, `IntFeasTol=1e-9`, the 900-second cap, physics, S10 and all
market/accounting semantics remain unchanged.

Plant applicability must now be frozen before solving. The 9+13 runner writes
one eligibility record per case and mechanism using only configuration, policy,
grid and ex-ante point support. It cannot use final periods, actual prices or
dispatch. Route substitution is `not_applicable` because the frozen route quota
does not prove headroom; this reason cannot be assigned ex post. Applicable
EAF/DRP and VN25/boiler/flare expectations, fixed-asset checks, economic
rationality and named material C1 response all enter the fail-closed gate.

Decision: `blocked_before_final_weeks_pending_full_behavioural_plant_gate`.
The next permitted broad solve is the non-final 9 synthetic plus 13 shadow
diagnostic. No final day, rolling validation week, four-week matrix, S30,
horizon, penalty, H2, mFRR or CVaR run may start before that gate passes.

## Parent-round bridge retained, but four-mask coverage is insufficient (2026-08-02)

Decision: an augmented-round parent plan may be used only in an auxiliary
restricted expected-cost bridge. The bridge fixes the preceding plan's
economic-scenario binaries, leaves feasibility-path binaries and shared bids
free, and is never result-eligible. All economic binaries are then unfixed and
the original full S10 expected-cost objective must again prove optimality. No
objective-preservation constraint is allowed. This keeps all ten scenario
prices and probabilities unchanged and gives every feasibility path zero
economic weight. The exact two-path diagnostic `20260802_s0c1_bridge_v2`
passes: bridge 11.861 seconds, complete expected-cost solve 372.184 seconds and
reduced canonical solve 73.740 seconds.

The end-to-end S0--C1 run
`20260802_s0c1_constraint_generation_bridge_v2` does not authorize the full
behavioural gate. One negative/low-price shadow mask is added after the four
initial violations are ranked. All four permitted QH shadow masks then have
proven zero minimum imbalance, but the controlled S0 actual mask still has a
proven 27.646412-MWh minimum upward-consumption imbalance. Its mask is not in
the four-pattern library and lies outside their per-lead rank envelope in 72
of 96 intervals. The reduced canonical tier also takes 903.536 seconds despite
returning optimal, exceeding the required below-900-second wall-time gate.
Emergency recourse is rejected, the penalty reconstructs exactly once at EUR
5,000/MWh, the run is non-resumable and no later or final case starts.

Decision: `blocked_before_final_weeks_requires_pattern_source_decision`.
Selecting another member of the same four-mask shadow library cannot cover the
failed S0 clearing because every member already passes its separation solve.
Admitting additional non-final validation masks or introducing a stronger
robust contract changes the explicitly frozen source scope and requires a new
methodological decision. No 9+13 rerun, rolling week, final day, final week or
excluded sensitivity is authorized meanwhile.

## Fixed 0.2% economic MILP-gap policy (2026-08-02)

Decision: use one fixed relative `MIPGap=0.002` only for explicitly named
economic cost tiers. Production progress, feasibility-only separation,
minimum imbalance, physical tie-breaks and every zero-imbalance gate retain
their stricter existing solve and acceptance rules. This is a solver policy,
not a gap sensitivity; EUR 5,000/MWh and all physical, scenario and market
contracts remain unchanged.

An economic time-limit incumbent is `epsilon_optimal` only when a finite loaded
objective, feasible incumbent and best bound exist, the independently computed
relative gap is at most 0.002, and downstream objective, clearing, settlement,
physical execution and zero-imbalance reconstruction pass. Every economic tier
records `[LB, UB]`, `UB-LB` and `(UB-LB)/abs(UB)`. Missing bounds or incumbent,
a larger gap, unknown/infeasible termination, or any reconstruction failure
remains fail-closed. For later minimisation-arm comparisons the certified
difference interval is `[LB_A - UB_B, UB_A - LB_B]`.

Historical diagnostic `20260802_s0c1_p3_focus2_v1` has UB EUR
9,694,749.389854, LB EUR 9,684,082.199056, band EUR 10,667.190798 and
certified gap 0.001100306. The numerical gap passes the new policy, but the run
did not persist bids, scenario/path dispatch, clearing, physical redispatch or
state handoff. It is therefore not reusable as an accepted plan; only the
smallest unfinished path-count-1 C1 cost/reconstruction gate may be rerun.

That minimal rerun is
`20260802_s0c1_path1_epsilon002_v1` and passes without final-period input. The
strict production tier is optimal in 17.074 s. The economic tier terminates
normally in 490.014 s with UB EUR 9,693,536.508257, LB EUR 9,683,839.208503,
band EUR 9,697.299754 and certified gap 0.001000388. Expected cost reconstructs
with zero error; maximum bid-clearing and feasibility-path errors are
3.32e-8 MWh and 5.68e-14 MWh. S10 probabilities and objective membership are
unchanged. Validation therefore resumes at the unfinished S0--C1 bounded
constraint-generation and zero-imbalance gate, not at any completed C0,
synthetic or shadow gate.

The resumed S0--C1 trajectory
`20260802_s0c1_constraint_generation_epsilon002_v1` also passes. Constraint
generation selects two non-final shadow masks in deterministic order:
negative/low (122.881657-MWh initial minimum violation), then typical/calm
(9.204178 MWh after round 1). After round 2 all five case-compatible validation
patterns have proven zero minimum imbalance. The final actual redispatch uses
exactly 0 MWh imbalance and skips the conditional minimum solve; all 48
physical/reconstruction checks pass.

Planning totals 199.625, 183.473 and 173.162 s for rounds 0--2. The final
two-path model has 109,992 variables, 2,448 binaries and 114,819 constraints.
Its economic certificate is LB EUR 9,676,898.062312, UB EUR
9,696,280.717435, band EUR 19,382.655123 and gap 0.001998978. Redispatch is
strictly physical with a separate economic certificate of LB EUR
8,484,703.202998, UB EUR 8,501,552.185900 and gap 0.001981871. A post-solve
summary KeyError was a reporting-only wrong-level lookup; persisted case,
solver and 48/48 check artifacts independently reconstructed PASS, and the
writer is regression-tested. No solve was repeated for that repair.

To avoid restarting the already completed S0 C0/C1 work, plant validation now
continues through one non-final manifest case per governed run. Each case
freezes its plant eligibility record before solving and writes physical,
behavioural and solver artifacts; cross-case plant/economic judgements remain
pending until the required comparison cases are aggregated. This continuation
mode cannot select a final-test case and cannot itself issue a cross-case PASS.
`S1_C0_responsive` passes at 0 MWh with 40/40 physical checks;
`S1_C0_price_insensitive` passes at 1.995e-6 MWh, inside the fixed 1e-5-MWh
numerical zero tolerance, also with 40/40 checks. Neither repeats an earlier
trajectory or reads final periods.

## Synthetic behavioural and plant continuation passes (2026-08-02)

Decision: preserve the fixed 0.2% economic-gap policy and accept only the final
hard-zero reconstructed solution. In `S3_C1_responsive`, an epsilon-optimal
economic incumbent with avoidable imbalance triggers the unchanged strict
minimum-imbalance tier. Because that tier proves zero, economics is re-solved
with `d_plus=d_minus=0`, its certificate passes, and the physical tie-break
again proves zero. The positive incumbent itself is never result-eligible.

The remaining synthetic continuation cases all pass: responsive and
price-insensitive S1 C1, responsive S2 C1, responsive S3 C1 and the S4 C1
true-PF benchmark each have 0 MWh and 48/48 physical/reconstruction checks.
Previously completed S0 and C0 cases are reused, not re-solved.

Cross-case aggregation must identify feasible sets from the frozen modelling
contract, not from realised terminal inventories. Constraint-generated and
ordinary cases now use the same terminal-band and physical-feasible-set hash.
Eligibility records may come from a separate pre-solve source root and are
deduplicated by case and mechanism. These are reporting/aggregation repairs;
they do not alter physics, scenarios, bids, prices, probabilities, the EUR
5,000/MWh penalty or maintenance assumptions.

`20260802_synthetic_plant_aggregate_epsilon002_v3` performs no solve and
returns `PASS` for 9/9 synthetic cases: no hard economic, plant or physical
failure and maximum imbalance 1.994853e-6 MWh. The next incomplete gate is the
thirteen-case non-final shadow/regime behavioural and plant validation under
the same method. The completed targeted shadow blocker is not repeated. Final
periods, the rolling validation week, the four-week matrix and all excluded
sensitivities remain unauthorized.

## Shadow PASS and frozen non-final rolling-week gate (2026-08-02)

Decision: the fixed 0.2% economic-gap, strict physical-tier and zero-imbalance
method passes the complete non-final behavioural population. Solve-free root
`20260802_shadow_plant_aggregate_epsilon002_v2` audits 13/13 current shadow
case artifacts and returns `PASS`, with zero hard economic/plant failures,
zero physical/financial failures, no emergency recourse and maximum imbalance
`2.2708565759e-6 MWh`. Combined with the already accepted synthetic aggregate,
the evidence is 9/9 synthetic and 13/13 shadow PASS. The aggregation itself
starts no solver and no final-test input is read.

Historical shadow results lacking complete numeric incumbent/bound and current
reconstruction artifacts are diagnostic-only and are not silently promoted.
The current runs exist because that evidence was not reusable under the fixed
epsilon certificate; no already completed current-code trajectory was rerun.
Responsive plans retain exactly ten scenarios and mass one. Price-insensitive
and true-PF benchmarks intentionally retain one path and mass one; they are not
misclassified as responsive S10 plans.

The next gate is frozen to 16--22 June 2025, a complete maintenance-free
non-final Monday--Sunday week selected before solving as the earliest supported
week after three frozen shadow sources. Only feasibility patterns whose source
delivery day is earlier than 16 June are eligible. The validation week itself
and the later high-price shadow case cannot augment it. This prevents
contemporaneous/future clearing-pattern leakage while preserving the unchanged
economic S10 prices, paths, probabilities and expected-cost objective.

The gate contains only C0/C1 times A-hourly, B-QH-flat and C-QH-shape: six
experiments, 42 executed days and seven daily state handoffs per experiment.
It uses 24-hour planning/execution, fixed EUR 5,000/MWh emergency recourse,
bounded maximum-three-round constraint generation for C1 and fail-closed
day/experiment stopping. It checkpoints after every day and aggregates daily
economic LB/UB certificates into the comparison interval
`[LB_A - UB_B, UB_A - LB_B]`. Static validation passes 111 relevant C6 tests,
Ruff and the solve-free preflight.

Current decision:
`blocked_before_final_weeks_pending_non_final_rolling_week`. The rolling solve
has not started; final days/weeks, the four-week matrix and every excluded
sensitivity remain unauthorized until this gate passes and the method freeze
is recorded.

Runtime governance for this gate is based on current matched C1 shadow evidence:
69.2 s for six hourly tiers, 715.1 s for twenty QH-flat tiers and 492.9 s for
fifteen QH-shape tiers. Seven days imply about 2.48 h of C1 solver time; with
C0, construction, persistence and changed-state separation the accepted
pre-run estimate is 3.0--3.5 h, approximately 390 tiers and 180--220 model
instances. The four central weeks project at least 12--14 h before separately
authorized benchmarks. Consequently the rolling gate starts only in a fresh
four-hour compute period and the final matrix remains a distinct later block.

## Rolling PASS, path-aware final executor and frozen method (2026-08-02)

Decision: accept `20260802_non_final_rolling_week_epsilon002_v1` as the final
non-final execution gate. It completes 42/42 rolling days and 6/6 C0/C1 A/B/C
experiments with 1,848 physical/financial checks and 11 hard plant checks, all
PASS. Maximum daily imbalance is `2.0000716411e-6 MWh`; no emergency recourse
or minimum-imbalance solve occurs. Weekly arm production differs by at most
`2.0000152290e-6 t`, and every state chain reaches 168 hours.

Measured wall time is about 55.2 minutes. The 279 completed tiers total
2,975.0 s; median, p95 and maximum tier runtimes are 0.782, 81.012 and 279.103
s. C1 daily planning plus validation-path separation has median 116.983 s,
p95 287.548 s and maximum 341.257 s. There are no time limits or unaccepted
tiers. Validation-week cost signs are reported as evidence and are not pass
conditions or final-regime claims.

Decision: the final representative executor must not use its former ordinary
C1 S10 planning call. It now invokes the already validated, bounded
constraint-generation planner with the same rolling state and bid variables.
The pinned non-final mask manifest has SHA-256
`ae24f756bc4de6ba7e2ed14256ab18f8852a5d8b44f95745443bcf8f66458220`.
Masks have no probability, expected-cost contribution, settlement eligibility
or forecast-metric role; they contain acceptance ranks/lead positions rather
than transported raw prices. The executor independently verifies that the
economic S10 contract hash and probability mass are unchanged. At most one
worst mask is added per round and at most three rounds are allowed. The fixed
EUR 5,000/MWh conditional minimum-imbalance gate remains the fail-closed final
safeguard.

Decision: freeze the method in
`scripts/Data/04_Steel_Test_Case/configs/steel_c6_final_method_freeze_v1.yaml`.
Its authorization-independent method identity is
`e34bdf490ffe800795b00423316e8c3c1618deb57006df0fba36513584c5d376`.
The existing final-week selection, maintenance-free assumption, D-only/S10
contract, 0.2% economic gap, strict physical tiers, pattern pool, thresholds,
output policy and checkpoint/stop rules may not change after authorization.
The runtime authorization itself remains false.

The long-run preflight is 24 central stochastic plus 32 benchmark experiments,
56 experiments and 392 daily trajectories. Projected wall time is 10--14
hours, using a fresh ignored thesis-candidate runroot and minimal outputs. No
final day has been solved in this engineering period. Current decision:
`path_feasibility_gate_pass_ready_for_final_week_authorisation`; wait for
explicit authorization before starting the final compute block.

Solve-free readiness audit decision: separate method identity from the runtime
authorization receipt. The runner previously hard-rejected every true
full-matrix flag, which would have required an avoidable code change after user
permission. The default remains closed and receipt-free. A future true state is
accepted only with an explicit timezone-aware receipt and the exact frozen
56-row central-plus-benchmark selection; partial sets, sensitivity rows,
different weeks, horizons, scenario counts, configurations, arms or maintenance
flags fail closed. The method payload and its hash do not include this external
authorization state. No final price input or solver was used for this audit.
