# C5 Rolling Production-Feasibility Optimiser

## Purpose and authority

This document defines the active price-free rolling-feasibility surface. Read
the current status and next gate in
`C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md` first.

The optimiser uses hard final-product-proxy quota deadlines, material
balances, carrier-specific WAG, represented steam/utilities and visible
residual reporting. It is not an annual site simulation or market optimiser.

## Active entrypoint

- runner: `run_s4_4c5p_ae_rolling_production_feasibility.py`;
- default config: `configs/steel_quota_driven_physical_feasibility.yaml`;
- comparable smoke run: `steel_quota_driven_physical_feasibility_v2`;
- thesis-scale config: `configs/steel_quota_driven_thesis_scale_feasibility.yaml`.

`steel_rolling_feasibility.yaml` and fixed C0 schedules are historical
diagnostic surfaces and are not active defaults.

## Frozen policy choices

| Topic | Active policy |
|---|---|
| Planning window | 168 hours |
| Execution/quota block | 24 hours |
| Smoke quota | 5,905.2 t final-product proxy per block |
| Thesis-scale quota | 18,493.150685 t/block, equivalent to 6.75 Mt/y over 365 days |
| Quota semantics | hard cumulative lower bound; overproduction is allowed and reported |
| C0 availability | `quota_driven_binary_capacity`; continuous classes must be enforced through the component ontology, not fixed hours |
| C1 availability | `quota_driven_topology` with source-classified continuous assets and bounded throughput |
| C0 coke interface | 1.285 t dry coal/t coke and 0.359 t coke/t hot metal; source-card-backed development coefficients |
| Sinter interface | activity is iron-ore feed in t/h; 1.230 t sinter/t iron ore is applied before inventory and per-t-sinter fuel/electricity terms |
| BF represented-sinter interface | 2.1041666667 t hot metal/t represented sinter; partial-burden development proxy, not a complete burden recipe |
| Production profile | chosen by the model from quota, topology, capacity and physical balances |
| WAG | BFG, COG and BOFG remain separate physical carriers |
| WAG/NG | eligible WAG first; named NG only where an accepted controller permits it |
| Mixed gas/Wobbe | out of scope |
| Electricity/NG residuals | reporting only; never inputs, allocations, calibration variables or costs |
| CO2 | Mode-B represented-fuel diagnostic only; no full Scope 1/ETS claim |
| Market terms | all disabled |

## Mathematical quota layer

For each deadline `d`:

```text
sum(final_product_output[t] for t < d) >= cumulative_quota[d]
```

The quota is a cumulative service level, not a forced flat production profile.
Continuous plants may remain available/on while their throughput stays within
source-backed operating envelopes. Batch-equivalent plants may schedule within
their governed bounds. No fixed route share or arbitrary active-hour count is
introduced.

Material stores retain their terminal and conservation conditions. A run may
not meet quota by depleting an unreported initial inventory or using residual
electricity, NG, coke, slab or WAG as hidden supply.

## Included physical scope

- C0/C1 topology and process capacity;
- coke, sinter, hot-metal, slab and final-product handoffs where represented;
- C1 DRI buffer and DRP/EAF material interface;
- BFG/COG/BOFG generation, governed sinks, flare and residual reporting;
- represented boiler/steam bridge and generator internal-electricity offset;
- named DRP and controller NG where explicitly modelled;
- solver, quota, material, WAG and boundary guardrails.

## Rolling execution status

The active p_ae smoke run is a 168-hour planning envelope and does not itself
perform repeated closed-loop execution. Gate 2 reused C5p_af for three
24-hour execution steps. The current Gate-4 comparison extends the same
mechanism to seven execution steps with repeated 168-hour replanning and
represented inventory handoff under the active quota-driven policy.

C0 passes all three steps at thesis scale with continuous-operation classes,
material balances and carrier-specific WAG guardrails intact. The zero-import
C1 case remains an expected-infeasible stresscase. The source-boundary-
reconciled MER-site case passes three C1 replans and all physical guardrails,
so Gate 2 is complete.

The evidence resolution retired the unlocated 1.10-t-slab/t-HRC broad proxy
from the active central case. The MER 6.8-Mt/y liquid-steel, 0.6-Mt/y slab-
import, 5.5-Mt/y HSM-output and 1.5-Mt/y DSP-output boundary implies an HSM
ratio around 1.06 at the retained 1.05 DSP conversion. EU FMP-BREF loss data
and a JICA 97.5%-yield engineering case independently support a lower ratio.
The accepted Gate-2 development central is therefore 1.06; it applies to all
HSM origins and excludes casting loss.

MER Table 5.2 resolves scrap as a 1.9-Mt/y central site-supply boundary, not a
technical melt cap. BOF has a 1.0-Mt/y consumer guardrail; EAF uses the central
0.9/3.3 scrap recipe and retains 1.8 Mt/y as its operational high-scrap upper
guardrail. The 2.8-Mt/y site value is a DRI-substitution variant at unchanged
steel output. Because the two route guardrails sum above 1.9 Mt/y, the site
allowance is not duplicated and no route split is fixed. Intermediate rolling
deadline caps prevent budget reuse while the static horizon cap enforces the
final deadline once.

`steel_gate2_closed_loop_mer_site_product_v5_20260716` solves optimally. Each
168-hour plan meets 129,452.054795 t and minimises import to 7,160.621929 t,
about 373,375 t/y horizon-equivalent. Executed imports are 273.972604,
1,643.835624 and 1,643.835624 t; the 72-hour annualised rate is
433,333.335327 t/y. Origin, material and separate BFG/COG/BOFG checks pass,
imported slab has zero upstream site burden and markets remain disabled.

The earlier 1.07-HSM/1.03-DSP solution remains a labelled
`development_feasibility_sensitivity`; it is not the central thesis
parameterisation. Gate 3 configuration-matched annual physical reconciliation
passes physically. Gate 4 corrects the v4 anchor interpretation and adds
separate seven-block `endogenous_feasibility` and `reference_validation`
modes. HSM input/output/loss, named NG, generator fuel, electricity and WAG
contracts are now explicit; reference production rows cannot validate
themselves and scoring is configuration-specific.

`steel_gate4_mer_reference_validation_week_v3_20260716` passes all rolling and
physical checks with 0.574321 Mt/y executed-week-equivalent import. Its stable
blocks annualise to 6.879436 Mt/y final product and its first planned horizon
to 6.75 Mt/y; neither is a simulated year. C0 HSM/DSP reference anchors remain
non-comparable because the executable C0 downstream route is not evidenced.
Corrected primary coverage is 0 of 4, with 3 contextual pairs. Two source-
bounded sensitivities pass but are not promoted. Gate 4 therefore stops before
costs; source/boundary evidence repair is next.

## Required outputs

Every active run reports:

- resolved configuration and input/code lineage;
- solver and termination status, runtime and model size;
- cumulative quota deadlines;
- C0/C1 availability policy and enforced continuous classes;
- material and origin conservation;
- carrier-specific WAG conservation and sink allocation;
- represented steam, electricity, named NG and residual fields;
- warnings, boundary caveats and infeasibility evidence.

Run outputs remain local under `data/03_Optimisation/runs/` unless explicitly
promoted as small thesis-critical provenance.

## Acceptance gate

The smoke stage passes only when both configurations solve, all quota and
material checks pass, carrier-specific WAG closes, residuals remain reporting
only and all market terms are disabled.

The thesis-scale gate additionally requires a configuration-matched result at
18,493.150685 t/day or a focused infeasibility diagnosis from the active
quota-driven model. A historic fixed-schedule failure does not satisfy this
diagnosis.

A pass does not unlock costs, DA, stochasticity, residual allocation or ETS.

Gate 1 passed after reconciling the sinter activity/output basis. Gate 2 passed
after reconciling the HSM input/output boundary and scrap-supply semantics.
C0 and MER-site C1 close seven representative-week replans with physical
guardrails; the zero-import C1 case remains an expected-infeasible stresscase.
Gate 3 has a passing physical ledger. Gate 4 has a corrected 0-of-4 primary
anchor-coverage gap and is complete with a pre-economics stop. Source/boundary
evidence repair is next. Economics, DA, stochasticity, mFRR and ETS remain
locked.
