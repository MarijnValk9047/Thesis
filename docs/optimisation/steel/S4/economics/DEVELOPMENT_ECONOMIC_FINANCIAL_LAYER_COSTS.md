# Development economic and financial cost layer

## Status and purpose

**Scope:** C0/C1 Tata Steel IJmuiden-inspired rolling physical model

**Use:** governed design specification for deterministic external-procurement costs

**Current model gate:** `DAM_data_contract_only_operational_gaps_remain`

**Price status:** development scenarios; not Tata procurement contracts

**Physical parameter authority:** the active model, source cards and machine-readable C5 contracts

This document defines which external flows may receive a price and how those
prices must be connected to the rolling MILP. It does not duplicate physical
conversion factors, plant efficiencies, annual production anchors or material
recipes. Those values remain authoritative in the active model inputs and
contracts.

The accepted implementation is fixed-reference, not endogenous route-choice
economics. Its current evidence is:

- price-free physical baseline:
  `steel_s2_fixed_reference_procurement_physical_v2_20260716`;
- complete ex-post baseline:
  `steel_s2_complete_ex_post_procurement_cost_v1_20260716`;
- central lexicographic cost run:
  `steel_s2_fixed_reference_deterministic_cost_v3_20260716`;
- same-lineage post-cost reconciliation:
  `steel_s2_post_cost_reconciliation_v2_20260716`;
- bounded sensitivity family:
  `steel_s2_fixed_reference_cost_sensitivity_v1_20260716`;
- flat/synthetic interface validation:
  `steel_s2_price_series_interface_validation_v1_20260716`; and
- final derived acceptance/explanation audit:
  `steel_s2_final_acceptance_explanation_audit_v1_20260717`; and
- corrected pre-DAM operational-boundary validation:
  `steel_s2_pre_dam_operational_boundary_closure_v1_20260720`.

The corrected central represented executed cost is EUR 34.232 million for C0
and EUR 61.047 million for C1 over 168 executed hours, or EUR 264.437/t and EUR
471.577/t site final product. These are represented external-procurement
scenario results, not total production costs or Tata procurement facts.

The two EUR/t values are not directly comparable total-production-cost or
route-economic results. The fixed C0/C1 scenarios contain different route
portfolios, generator interfaces, imported-slab and DR-pellet exposure. Both
retain an explicit BF-pellet scope gap and C1 HBI is inactive. They may be
shown side by side only as represented-boundary scenario waterfalls.

The corrected central rolling execution produces 6.75 Mt/y equivalent. A
cumulative production-progress tier carries completed production credit/debt
into later replans, so the former 6.78375-Mt/y repeated-first-block diagnostic
is no longer the central executed result. Hourly production remains endogenous
inside the unchanged fixed-reference envelope.

The central rule is:

```text
cost[flow, t] = solved_external_quantity[flow, t] * price[price_id, t]
```

No cost-input file may independently reconstruct the external quantity from a
plant output, an annual anchor or a copied conversion coefficient.

## 1. Authoritative model interfaces

Before implementing or changing a cost term, use the current versions of:

- `docs/optimisation/steel/S4/C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md`;
- `data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/c5_route_boundary_contract.csv`;
- `data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/c5_future_cost_boundary_contract.csv`;
- `docs/optimisation/PROJECT_DECISIONS.md`;
- `docs/optimisation/model_equations.md`;
- the active unified physical modelbuilder and its selected input tables.

If a coefficient in an older note conflicts with one of these active sources,
the older coefficient is not copied into the cost layer. The cost layer prices
the solved flow produced by the active model.

This policy deliberately removes duplicated calculations such as:

- tonnes of coal per tonne of coke;
- coke or PCI per tonne of hot metal;
- pellets or natural gas per tonne of DRI;
- scrap per tonne of BOF/EAF output;
- slab-to-HRC conversion;
- annual cost examples based on raw production anchors;
- duplicate EUR/GJ values derived from an EUR/MWh input.

These calculations belong to the physical model or to reporting derived from
the solved physical ledger, not to the cost-input specification.

## 2. Economic layers

The project must keep four layers separate.

### 2.1 Variable external procurement: operational objective

Only named external purchases whose physical flow is represented in the MILP
may enter the deterministic operational objective.

Candidate families are:

- represented net grid-electricity import;
- represented named natural-gas purchases;
- purchased coking coal;
- purchased PCI coal;
- purchased iron ore;
- imported BF-grade pellets;
- imported DR-grade pellets;
- purchased scrap;
- imported slab;
- other explicitly active external material flows.

### 2.2 Variable operating costs: optional later extension

Throughput-dependent maintenance, electrodes, refractories, lime, oxygen
service or other variable O&M may be added only when both a named physical
driver and a source-backed unit cost exist. They are not approximated through a
generic cost per tonne of steel.

### 2.3 Carbon-policy costs: separate sensitivity

Mode-B emissions may be valued ex post for a labelled partial-boundary
sensitivity. ETS is excluded from the base objective until the represented
carbon boundary is suitable for route-comparative optimisation and avoids all
aggregate-counter double counting. Free allocation and CBAM remain separate.

### 2.4 Financial appraisal: outside the rolling dispatch objective

Annualised CAPEX, fixed O&M, labour, financing and other fixed costs belong in
an ex-post annual financial comparison. They do not affect hourly dispatch when
the asset configuration is fixed. They may enter the MILP only in a future
investment-choice formulation.

## 3. Base policies

| Policy | Base setting | Reason |
|---|---|---|
| Fixed production quota | enabled | Compare the cost of meeting the governed production requirement. |
| Product revenue | disabled | Production is quota-driven, not revenue-seeking. |
| Internal WAG price | disabled | BFG, COG and BOFG gain value only by avoiding external purchases. |
| Mixed or aggregate WAG price | prohibited | These are not physical procurement carriers. |
| Steam price or revenue | disabled | Steam is an internal utility balance. |
| Internal generator revenue | disabled | Generation offsets represented grid import; there is no export market. |
| Residual electricity/NG cost | prohibited | Residuals are reporting gaps, not dispatch variables or purchases. |
| ETS in base objective | disabled | Mode B is partial and is not a complete ETS/Scope-1 ledger. |
| Free-allocation credit | disabled | Requires a separate benchmark/activity module. |
| CBAM | deferred | Outside the first deterministic operational layer. |
| Fixed-reference cumulative route bands | enabled only in fixed-reference cost mode | Preserve the governed scenario without fixing hourly throughput or permitting economic route substitution. |

Internal WAG can influence the result without receiving a price:

```text
more useful eligible WAG allocation
    -> less represented grid import and/or named NG
    -> lower external procurement cost
```

No fixed WAG/NG ratio, mixed-gas carrier or Wobbe constraint is introduced.

## 4. Price scenarios

### 4.1 General price rules

- Store executable prices in EUR using one canonical unit per carrier.
- Freeze every scenario with a scenario ID, validity period, source vintage and
  delivery/quality basis.
- Do not auto-refresh prices inside a thesis run.
- Do not store low, central and high as three simultaneously active prices.
- Do not hardcode prices in Python.
- Do not store derived unit duplicates as independent inputs.
- Market proxies are not Tata contract prices.
- Freight, quality premiums, network charges and taxes must be explicit in the
  price basis; never assume silently that a quoted benchmark is delivered to
  IJmuiden.

### 4.2 Development price register

| `price_id` | Low | Central | High | Canonical unit | Initial use | Status and basis |
|---|---:|---:|---:|---|---|---|
| `grid_electricity_flat_nl` | 50 | 80 | 110 | EUR/MWh_e | Base deterministic S2 price | Governed flat wholesale-development scenario. Central is a rounded Dutch day-ahead context value; later replaced by a time series without changing the flow mapping. |
| `natural_gas_ttf_proxy` | 30 | 55 | 80 | EUR/MWh_LHV | Named NG only | Development TTF/EU wholesale proxy; exclude residual NG. |
| `coking_coal_hcc_proxy` | 150 | 205 | 260 | EUR/t purchased dry coal | Active fixed-reference procurement | Imported HCC benchmark proxy; never price internal coke as well. |
| `pci_coal_proxy` | 110 | 145 | 180 | EUR/t purchased PCI | Sensitivity after named-flow activation | Public PCI evidence is weaker; thermal coal is not an exact PCI substitute. |
| `iron_ore_62fe_proxy` | 80 | 90 | 110 | EUR/t purchased ore | Active represented sinter/PEFA boundary | Benchmark proxy retaining a delivered-quality caveat. |
| `imported_bf_pellets_proxy` | 115 | 140 | 180 | EUR/t imported BF pellets | After origin-specific flow exists | Iron-ore plus pellet-premium proxy. |
| `imported_dr_pellets_proxy` | 140 | 180 | 240 | EUR/t imported DR pellets | Active explicit purchased/imported DRP boundary | DR-grade quality sensitivity; do not apply to internally produced pellets. |
| `purchased_scrap_proxy` | 280 | 330 | 380 | EUR/t purchased scrap | Active represented-boundary assumption | No internal recycle share is asserted; later recycle-loop work may split origins. |
| `imported_slab_proxy` | 420 | 530 | 570 | EUR/t imported slab | Full procurement objective/sensitivity | Apply only to actual solved imported slab, never to the 0.6-Mt/y cap. |
| `hbi_import_proxy` | 300 | 350 | 450 | EUR/t imported HBI | Inactive route sensitivity | No base HBI import flow is active. |
| `quicklime_proxy` | 140 | 170 | 215 | EUR/t purchased quicklime | Deferred | Activate only if an explicit external lime flow is present. |
| `ets_eua_partial_mode_b` | 60 | 79 | 100 | EUR/tCO2 | Ex-post sensitivity only | Never label as full Tata ETS cost. |

The electricity central value is deliberately rounded to EUR 80/MWh. The
initial implementation is price-flat so that route and accounting behaviour can
be tested without day-ahead timing effects. A later DAM scenario changes:

```text
price_series_id = flat_central_reference_v1
```

to an hourly or quarter-hourly Dutch day-ahead series. It does not change the
priced physical flow:

```text
represented_net_grid_import_mwh[t]
```

The governed interface contract is `c5_price_series_contract.csv`. Each slice
contains delivery and information-availability timestamps, market area,
currency/unit, resolution, forecast classification and missing-price policy.
Only information available by the replan timestamp is eligible. Executed-block
price fields are interface metadata, not settlement. The synthetic series is
indexing evidence only; no real DAM data are active.

### 4.3 Price-source context

Candidate public sources include:

- EPEX SPOT Dutch day-ahead indices for electricity;
- TTF/EU wholesale gas benchmarks;
- hard coking-coal and PCI benchmark proxies;
- 62% Fe iron-ore and pellet-premium methodologies;
- LME/Platts CFR Turkey scrap as a proxy;
- European/CFR slab reporting;
- EUA market prices for carbon sensitivity.

Every executable scenario row must record its exact source and observation
date. Current web values in a narrative note are not executable inputs.

## 5. Flow-to-price contract

The cost layer must map prices to solved flow IDs, not reconstruct quantities.

| Cost family | Solved quantity required | Current readiness | Required action |
|---|---|---|---|
| Grid electricity | represented net grid import by configuration and timestep | `objective_ready` | Add flat price scenario, later DAM series. |
| Named NG | sum of represented named NG consumers on MWh-LHV basis | `objective_ready` | Price each named flow once or price their governed sum once. |
| Imported slab | actual imported slab delivered to HSM | `objective_ready_with_proxy_price` | Remove old import-minimisation objective in economic mode; retain physical cap. |
| Purchased coking coal | external dry-coal purchase to KGF | `objective_ready` | Active solved dry-coal flow is priced once; internal coke is unpriced. |
| Purchased PCI | named external PCI flow to BF | `objective_ready` | Active accounting flow follows solved hot-metal output; no burden substitution is claimed. |
| Purchased iron ore | external ore to represented sinter/PEFA processes | `objective_ready_with_partial_burden_caveat` | Represented ore is priced; unrepresented BF pellets remain an explicit non-free scope gap. |
| Imported BF pellets | explicit imported BF-pellet flow | `explicit_scope_gap_not_free` | No active physical flow exists; close before a complete burden or endogenous route-cost claim. |
| Imported DR pellets | explicit DRP pellet import flow | `objective_ready` | All solved DRP pellets are represented as purchased/imported because no PEFA-to-DRP material link exists. |
| Purchased scrap | purchased BOF/EAF scrap | `objective_ready_development_boundary` | All represented scrap is purchased because no internal recycle loop exists; do not invent a recycle fraction. |
| Imported HBI | explicit HBI import flow | `inactive_route` | No price term in base. |
| Quicklime/flux | explicit external flux flow | `inactive_or_deferred` | No price term until physical flow exists. |
| Mode-B CO2 | represented non-overlapping oxidation ledger | `reporting_ready_partial` | Ex-post sensitivity only. |

### 5.1 No-double-counting examples

- Price KGF purchased coal or purchased coke, never both. The active model uses
  KGF coal input and internal coke transfer, so internal coke has no second
  purchase price.
- Price purchased ore feeding internal PEFA and the other external PEFA inputs;
  do not also assign an imported-pellet price to the internally produced pellet.
- Price only the purchased part of scrap.
- Price actual imported slab; do not price slab inventory or an import cap.
- Price represented grid import; do not additionally price all named electricity
  demand buckets.
- Price named NG; do not additionally price the full-site NG residual.

## 6. Deterministic objective

Let:

- `Q[f,t]` be the solved quantity of an eligible external flow;
- `P[p,t]` be the selected price scenario value;
- `price_of[f]` map each external flow to one price ID;
- `F_cost` contain only flow rows with `objective_enabled = true`.

The primary objective is:

```text
minimise represented_external_procurement_cost
    = sum(t in planning_horizon,
          sum(f in F_cost,
              Q[f,t] * P[price_of[f],t]))
```

For quantities stored as rates, multiply by the timestep duration exactly once.
For quantities already stored per timestep, do not multiply again.

The accepted fixed-reference set is:

```text
F_cost = {
  represented_grid_import,
  represented_named_NG,
  purchased_dry_coking_coal,
  purchased_PCI,
  represented_purchased_ore,
  purchased_or_imported_DRP_pellets,
  represented_purchased_scrap,
  actual_imported_slab_to_HSM
}
```

BF pellets remain outside `F_cost` because the active physical burden does not
expose that flow. HBI remains outside because no import route is active.

### 6.1 Lexicographic physical tie-breaker

Do not mix arbitrary physical penalties into euro costs. Solve sequentially:

1. minimise external procurement cost;
2. constrain cost to `best_cost + solver_tolerance`;
3. minimise the existing physical tie-breaker terms, including unnecessary
   overproduction, flare, avoidable inventory cycling and unresolved output.

Hard production quota, capacities, operating classes, material/origin balances,
carrier-specific WAG balances, steam, utilities, inventories and rolling
handoffs remain constraints in both solves.

## 7. Rolling-horizon accounting

- Optimise the complete 168-hour planning horizon.
- Execute and book only the first 24-hour block.
- Replan from the executed terminal state.
- Sum only executed-block costs in realised rolling reports.
- Never sum overlapping 168-hour planning objectives as annual cost.
- Keep planned-horizon cost and realised executed-block cost as separate fields.
- Reference-validation mode must not emit an economic result.

The initial flat prices intentionally contain no future DAM information. Later
dynamic price runs must preserve information timing and be labelled separately
from the flat deterministic procurement benchmark.

## 8. Route-cost coverage gate

An endogenous route comparison is not economically interpretable until all
major represented external inputs that distinguish the routes are priced or
explicitly excluded for both routes.

Minimum coverage:

### BF-BOF route

- purchased coking coal;
- purchased PCI;
- represented ore/pellet burden;
- purchased BOF scrap;
- represented grid electricity;
- represented named NG;
- any imported BF pellet flow that is active.

### DRP-EAF route

- imported/purchased DR pellets or another explicit pellet origin;
- purchased EAF scrap;
- represented grid electricity;
- represented named NG;
- HBI only if the import route is activated.

### Imported-slab downstream route

- actual imported slab;
- represented downstream grid electricity;
- represented downstream named NG.

If one route lacks a major procurement boundary, the model may run a cost
accounting diagnostic but must not claim an economically optimal route split.

## 9. Input-table design

### 9.1 `external_supply_costs.csv`

Store prices only:

```text
price_id
scenario_id
carrier_or_material
value
unit
currency
price_type
valid_from
valid_to
observation_date
delivery_basis
quality_basis
source_title
source_url
source_locator
source_status
thesis_usability
caveat
```

Do not store physical conversion factors, annual quantities, cost per tonne of
plant output or precomputed annual costs in this table.

### 9.2 Cost-flow mapping

Extend the existing `c5_future_cost_boundary_contract.csv` rather than creating
a second boundary register. Required cost fields include:

```text
flow_id
price_id
objective_enabled
objective_mode
external_purchase_status
origin_status
physical_quantity_attribute
physical_unit
price_unit
unit_compatibility_status
double_count_group
cost_readiness_status
deferred_reason
```

### 9.3 `cost_policy_modes.csv`

Required base rows:

```text
product_revenue_enabled = false
internal_wag_price_enabled = false
mixed_or_aggregate_wag_price_enabled = false
steam_price_enabled = false
generator_export_revenue_enabled = false
residual_electricity_cost_enabled = false
residual_ng_cost_enabled = false
ets_in_base_objective = false
free_allocation_enabled = false
cbam_enabled = false
reference_bands_enabled_in_economic_mode = false
```

## 10. Implemented sequence and next boundary

The price/policy schema, complete ex-post ledger, once-only grid/NG/slab and
material mappings, route-cost coverage gate, lexicographic fixed-reference
objective, bounded price sensitivities and flat/synthetic price-series
interface are complete. The route-cost coverage label is
`adequate_represented_major_inputs_with_explicit_scope_gaps`; it does not
authorise endogenous route selection or a total-production-cost claim.

The next permitted DAM task is a governed price-data and forecast contract
only. It
may replace the flat electricity series only after defining source vintage,
delivery and information-availability timestamps, units, market area,
resolution, forecast/realised classification and missing-price policy. Real
DAM optimisation, bidding and settlement require a later gate and are not yet
authorised for design: VN25 unit-operation evidence, the quantitative IJ01 CHP
contract and the active BF-pellet burden remain open. ETS and annual financial
appraisal remain separate later layers.

## 11. Acceptance tests

### Cost identity and units

- Every priced row has one external physical flow and one compatible price.
- Every active price unit matches its physical quantity unit.
- The sum of component costs equals the primary objective within tolerance.
- No rate/quantity timestep conversion is applied twice.

### Double counting

- Gross electricity buckets are not priced in addition to grid import.
- Named NG is not priced in addition to residual NG.
- KGF coal and internal coke are not both priced.
- Internal PEFA pellets and imported pellets are not both priced for the same
  tonne.
- Internal and purchased scrap remain distinguishable.
- WAG, steam, generator output and slab inventory have zero direct price.

### Physical guardrails

- Production quota, material, origin, inventory, steam and utility checks pass.
- BFG, COG and BOFG balances pass separately.
- `aggregate_wag_physical_use = 0`.
- `mixed_wag_quantitative_use = 0`.
- Residual electricity and NG never become model inputs.
- Mode-B and aggregate process counters are never combined.

### Economic behaviour

- Higher imported-slab price cannot increase slab import unless another changed
  constraint or price explains it.
- Higher NG price cannot create additional named NG use without a documented
  physical trade-off.
- Higher purchased-scrap price cannot increase purchased scrap without a
  documented route trade-off.
- Internal WAG can reduce external cost but never creates direct revenue.
- No-export electricity remains enforced.
- Economic mode uses endogenous routing and no reference-validation bands.

### Rolling and solver reporting

- Only executed-block costs enter realised totals.
- Planning and executed costs are separate.
- Gurobi status, termination, objective, best bound, MIP gap, runtime, variable
  count, binary count and constraint count are reported.
- The price-free physical baseline remains reproducible and unchanged.

## 12. Required reporting

Report at least:

- procurement cost by external carrier/material;
- procurement cost by model component and route;
- represented grid-electricity and named-NG cost;
- actual imported-slab cost;
- purchased-material cost once activated;
- total represented variable procurement cost;
- represented cost per tonne site final product;
- internal-generation grid-cost offset;
- WAG allocation and avoided external purchase, without WAG revenue;
- residual electricity/NG quantities excluded from cost;
- price scenario ID, source vintage and boundary caveats;
- excluded cost families;
- route-cost coverage status;
- optional partial Mode-B carbon-cost sensitivity, clearly separated.

The result must be described as `represented-boundary deterministic variable
procurement cost`, not total Tata site cost, full production cost, profit or
business-case NPV.

## 13. Source register

Physical evidence remains in the project source cards and active machine-
readable contracts. Candidate public price sources include:

- EPEX SPOT market results and indices: https://www.epexspot.com/en/market-results
- ACER electricity and gas market monitoring: https://www.acer.europa.eu/monitoring
- Eurostat non-household energy-price statistics: https://ec.europa.eu/eurostat/web/energy/database
- EU ETS and free-allocation policy: https://climate.ec.europa.eu/eu-action/carbon-markets/eu-emissions-trading-system-eu-ets_en
- coking-coal benchmark context: https://www.spglobal.com/energy/en/pricing-benchmarks/assessments/metals/premium-low-vol-coking-coal-price-explained
- iron-ore and pellet methodology context: https://www.spglobal.com/commodityinsights/en/our-methodology/methodology-specifications/metals/iron-ore-methodology
- LME Steel Scrap CFR Turkey: https://www.lme.com/metals/ferrous/lme-steel-scrap-cfr-turkey-platts
- ECB exchange-rate reference: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html

Public market sources remain proxies. Every executable scenario must retain its
own dated source locator and delivery/quality caveat.
