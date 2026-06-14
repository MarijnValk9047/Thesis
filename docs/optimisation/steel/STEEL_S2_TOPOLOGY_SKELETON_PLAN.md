# Steel S2 Topology Skeleton Plan

## Purpose

This note records the planned structural topology boundary for `S2.6b`.

It is a planning memo only. It does not:

- create executable topology input files;
- approve numerical values;
- implement `S2.6b`;
- reopen `S3`, DA, stochastic, `mFRR`, `CVaR`, or horizon-comparison logic.

The purpose is to state clearly what the deterministic `S2` topology skeleton is expected to contain once implementation begins, while keeping the current work purely structural and non-executable.

Read this together with:

- `STEEL_CONFIGURATION_SCOPE_FREEZE.md`
- `STEEL_S2_CONFIGURATION_TAG_MAPPING.md`
- `STEEL_S2_S3_IMPLEMENTATION_SCOPE.md`
- `STEEL_S2_STRUCTURAL_NUMERICAL_SEPARATION.md`
- `STEEL_S2_UNIT_SIGN_AND_ENDPOINT_CONVENTIONS.md`

## Planning Boundary

The planned `S2.6b` topology skeleton is limited to:

- deterministic hourly metallic material-flow structure only;
- `C0` and `C1` as the only main structural configurations;
- `C1S` as sensitivity dimensions only;
- `C2` as optional later boundary only;
- fixed production target logic;
- structural buffer and endpoint policy only.

It excludes:

- `S3` WAG and internal-energy structure;
- ETS, free allocation, `CBAM`, or tariff logic;
- DA prices, bidding, settlement, stochastic scenarios, `mFRR`, `CVaR`;
- `15-minute`, `D_only`, or `D_plus_4` comparison logic;
- product revenue or order-book logic.

## Planned `C0` Structural Elements

`C0_current_BF_BOF_reference` is planned as the current-route reference topology.

Expected structural elements:

- retained `BF_BOF` route;
- retained converter block;
- downstream casting split or aggregate transfer hub;
- downstream `DSP` and `WBW` sink treatment as coarse structural sinks;
- small or tightly bounded hot-metal transfer or buffer class if required for physical feasibility;
- no `DRP` or `EAF` route active in the main `C0` structure.

Interpretation:

- `C0` exists for validation, reference, and current-versus-future contrast;
- it is not the main future flexibility case.

## Planned `C1` Structural Elements

`C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` is planned as the main thesis steel topology.

Expected structural elements:

- retained `BF_BOF` route fragment;
- retained converter block;
- added `NG_DRP_EAF` route fragment;
- retained downstream casting and slab-processing coupling;
- retained or aggregated downstream sink structure for `DSP` and `WBW`;
- explicit structural coupling between upstream route outputs and downstream sink or buffer logic.

Expected flexibility-relevant structure:

- `EAF` route fragment;
- `DRI` or `HDRI` surge or decoupling buffer;
- slab or downstream `WIP` buffer;
- bounded downstream coupling that allows operational shifting without fake inventory creation.

## Planned `C1S` Sensitivity Dimensions

`C1S_phase1_sensitivity_variants` is planned only as structural sensitivity space inside the same `C1` topology.

Allowed sensitivity dimensions include:

- `DRI` or `HDRI` buffer activation or sizing class;
- slab or downstream `WIP` buffer activation or sizing class;
- `EAF` sizing class;
- `DRP` turndown handling class;
- `EAF` batch-equivalent simplification class;
- scrap-share handling class;
- selected exogenous closure or sink-policy toggles if they do not create a new pathway family.

These are structural planning dimensions only. No values are approved here.

## Optional `C2` Boundary

`C2_exogenous_hydrogen_sensitivity_optional_later` remains outside the main `S2.6b` path.

If opened later, it should mean only:

- same `C1` topology;
- hydrogen as an exogenous availability or input condition;
- no on-site electrolyser;
- no hydrogen production optimisation;
- no hydrogen storage or infrastructure optimisation.

`C2` is therefore a later boundary note, not a structural implementation branch for the first topology skeleton.

## Planned Internal Buffers In S2

The expected `S2` buffer policy is intentionally narrow.

### Hot-Metal Buffer

Planned interpretation:

- small and tightly bounded;
- used only to capture short transfer or feasibility-relevant decoupling;
- not a large arbitrage inventory.

### DRI or HDRI Buffer

Planned interpretation:

- bounded;
- physically explicit if activated;
- subject to `CYC50` endpoint policy;
- intended as a real flexibility-relevant buffer for `C1`, not as unlimited inventory.

### Slab Or WIP Buffer

Planned interpretation:

- bounded;
- downstream-coupling or decoupling role only;
- subject to `CYC50` endpoint policy;
- may represent hot slab, cold slab, or coarse `WIP` class depending on the later structural choice.

### Liquid Steel Or Hot-Slab Treatment

Planned interpretation:

- tiny, transient, or feasibility-only treatment unless stronger structural justification is added later;
- not a large discretionary storage block in the first topology skeleton.

### Coke, Sinter, And Pellet Internal Buffers

Planned interpretation:

- omitted from the first main `S2` topology skeleton;
- or left as sensitivity-only ideas, not main flexibility buffers;
- external supply treatment is preferred unless stronger public evidence later justifies explicit bounded internal stock.

## External Raw-Material Supplies

The first topology skeleton should treat raw-material feeds primarily as external supplies, not as internal flexibility buffers.

Examples:

- coal or coke-equivalent supply;
- iron ore;
- pellets;
- scrap;
- fluxes and similar metallic-process consumables.

Structural rule:

- external supply sources may feed route units;
- they should not be modelled as internal arbitrage inventories by default in the first `S2` skeleton.

## Fixed Production Target Logic

The planned `S2` topology skeleton still assumes:

- fixed production target policy;
- material-balance feasibility first;
- no endogenous product-revenue objective.

That means the topology skeleton must support:

- route throughput variables;
- production fulfilment accounting;
- shortfall or infeasibility diagnostics where required;
- downstream sink consistency under the fixed-target policy.

## CYC50 Endpoint Policy

The planned endpoint policy for the main internal buffers is `CYC50`:

- initial inventory equals `50%` of explicit buffer capacity;
- terminal inventory equals initial inventory;
- cyclic endpoint treatment prevents fake flexibility from one-sided depletion.

At `S2.6a`, this is still a structural planning rule, not an approved numerical input set.

## Explicit Non-Scope For The Skeleton

The first topology skeleton must not include:

- `S3` WAG layers;
- energy-economics logic;
- emissions-cost logic;
- DA price-taking or bidding logic;
- stochastic scenarios;
- `mFRR`;
- `CVaR`;
- product revenue;
- order-book or deadline logic;
- `D_only` versus `D_plus_4` comparison artifacts.

## Expected Future Implementation Files For `S2.6b`

These are planning notes only. They are not created in this task.

Likely future implementation surfaces include:

- a structural topology registry module under `scripts/Data/04_Steel_Test_Case/steel/`;
- a topology-builder or topology-normalisation module under the same steel package;
- topology-focused tests under `scripts/Data/04_Steel_Test_Case/tests/`;
- parse-only or structural-only config entries for `C0` and `C1`;
- non-executable candidate-review linkage checks for route and buffer coverage.

Any future file creation must still respect:

- non-executable governance until approved inputs exist;
- no hardcoded steel parameters in Python;
- no topology branch proliferation beyond the frozen configuration set.
