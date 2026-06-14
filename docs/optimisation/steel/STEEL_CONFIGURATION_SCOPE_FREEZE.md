# Steel Configuration Scope Freeze

## Purpose

This note records `S2.5e`: the steel configuration-scope freeze for the `S`-phased implementation plan.

Its job is to freeze the small configuration set that the thesis is actually allowed to build around before any `S2.6` topology skeleton, executable input promotion, or later DA / stochastic / reserve implementation.

This is a scope and governance decision only. It does not:

- create executable steel configurations;
- approve numerical values;
- reopen `S3` through `S9`;
- introduce `D_only` versus `D_plus_4` comparison logic;
- turn the thesis into a transition-pathway competition study.

Read this together with:

- `STEEL_IMPLEMENTATION_FREEZE_V1.md`
- `STEEL_IMPLEMENTATION_ROADMAP.md`
- `STEEL_MODEL_POLICY_DECISIONS.md`
- `STEEL_S2_S3_IMPLEMENTATION_SCOPE.md`
- `STEEL_TRACTABILITY_AND_CHANGE_CONTROL.md`
- `STEEL_S2_STRUCTURAL_NUMERICAL_SEPARATION.md`
- `STEEL_S2_DEEPSEARCH_F_NUMERICAL_ASSUMPTION_LIBRARY.md`

## Why The Thesis Uses A Small Configuration Set

The thesis question is not "which steel transition pathway is best?".

The thesis question is whether operational flexibility and market participation create value under a credible electrified steel configuration, and whether forecast or scenario quality changes that value.

That requires a small and stable physical configuration set because:

- forecast-quality comparisons become weak if the plant topology also changes between runs;
- tractability falls quickly if every transition pathway becomes a separate plant model;
- stage-gate validation is easier when the same core topology is reused from deterministic `S2` through later market stages;
- thesis writing is cleaner when sensitivities stay inside one main future case instead of becoming many competing future worlds.

This freeze therefore blocks uncontrolled pathway proliferation and keeps the steel workstream focused on a narrow current-versus-future flexibility contrast.

## Frozen Configuration Set

### `C0_current_BF_BOF_reference`

Definition:

- current `BF_BOF` reference configuration;
- used for validation, reference, and contrast;
- included to show the limited operational flexibility of the current route;
- not the main market-flexibility thesis case.

Allowed role:

- `S2` and later stages may use `C0` as the current-route contrast case;
- it remains part of the frozen physical configuration set;
- it must not be reframed as the main future flexibility case.

### `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`

Definition:

- main thesis steel configuration;
- Tata IJmuiden-inspired Phase 1 hybrid route;
- retains a `BF_BOF` route and adds an `NG_DRP_EAF` route;
- `DRP` is natural-gas-based in the base case;
- hydrogen-ready context may be documented, but hydrogen is not the endogenous steel-model base case.

Main flexibility sources in `C1`:

- `EAF` operation;
- `DRI` or `HDRI` decoupling buffer where structurally allowed;
- slab or downstream `WIP` buffering;
- coupling between upstream route choice and downstream processing.

Allowed role:

- this is the main configuration for later deterministic DA, stochastic DA, `mFRR`, and risk stages after the earlier gates pass;
- this is the only main future steel configuration in the thesis implementation path.

### `C1S_phase1_sensitivity_variants`

Definition:

- sensitivity variants within the same `C1` topology only;
- not a separate transition pathway family.

Allowed sensitivity dimensions include:

- `DRI` buffer size;
- slab or `WIP` buffer size;
- `EAF` sizing;
- `DRP` turndown;
- `EAF` batch-equivalent assumptions;
- scrap share;
- other explicitly approved sensitivity dimensions within the same topology.

Boundary rule:

- `C1S` may change parameterisation or bounded operating assumptions inside `C1`;
- `C1S` may not create a new pathway model with a different route family.

### `C2_exogenous_hydrogen_sensitivity_optional_later`

Definition:

- optional later sensitivity only;
- same `C1` topology;
- hydrogen may appear only as an exogenous reducing-gas or fuel input if time allows.

Hard limits:

- no on-site electrolyser;
- no hydrogen storage or infrastructure optimisation;
- no endogenous hydrogen production optimisation;
- not a main thesis configuration.

`C2` is therefore a narrow later sensitivity layer, not a hydrogen-steel redesign of the thesis.

## What Is Explicitly Out Of The Main Configuration Set

The following are blocked from the main `S2` to `S9` implementation path unless a methodological change is declared explicitly:

- Phase 2 transition configuration;
- Phase 3 transition configuration;
- full hydrogen steel plant as the main case;
- on-site electrolysis as part of the steel configuration;
- hydrogen production optimisation inside the steel model;
- SAF, CCS, or full pathway optimisation as main thesis cases;
- technology pathway comparison as the thesis objective.

These items may be discussed as context, boundary conditions, or later research directions. They are not part of the frozen main thesis configuration set.

## Why Hydrogen Is Exogenous Later, Not Endogenous Now

Hydrogen is not frozen as an endogenous steel-model production block because that would reopen a different research problem:

- electrolyser sizing and dispatch;
- hydrogen storage logic;
- infrastructure and availability logic;
- coupling between power procurement and reducing-gas production.

That would shift the thesis away from a controlled electrified-steel flexibility case and back toward a broader hydrogen-system design problem.

The frozen position is therefore:

- base `C1` uses `NG_DRP_EAF`;
- hydrogen may enter later only as an exogenous sensitivity in `C2`;
- endogenous hydrogen production remains out of scope for the steel configuration freeze.

## Link To The S-Phased Implementation Plan

This freeze preserves the existing `S1` to `S9` sequence.

Implementation direction is:

1. `S2` and `S3`: build the deterministic steel structure around `C0` and `C1` only;
2. later DA, stochastic, reserve, and risk stages: carry the same frozen configuration logic forward;
3. use `C1S` only for bounded sensitivity work within `C1`;
4. treat `C2` as optional later exogenous-hydrogen sensitivity only if earlier gates pass.

This prevents `S2.6` and later stages from drifting into a many-pathway plant family before the core model is even validated.

## Sensitivities Inside C1 Versus Separate Transition Pathways

The central distinction is:

- `C1S` changes assumptions inside the `C1` topology;
- separate transition pathways change the topology family itself.

Examples of allowed `C1S` work:

- a larger or smaller `DRI` buffer;
- higher scrap share within the same `EAF` route logic;
- different bounded `DRP` turndown assumptions.

Examples blocked as separate pathway work:

- replacing `NG_DRP_EAF` with a different transition route family as a new main case;
- building Phase 2 and Phase 3 as peer thesis configurations;
- recasting the thesis as full pathway optimisation.

## How This Prevents Scope Creep

This freeze explicitly prevents drift from a focused operational-flexibility thesis toward an Athanasiadis-style transition-pathway modelling exercise.

The repository may still track transition context, but future implementation must not multiply plant futures into the main coding path. The frozen rule is:

- small configuration set for the thesis core;
- sensitivity work inside `C1`;
- pathway expansion only through an explicit methodological reopening.

## Relation To Badarinath-Style Framing

The current-versus-future contrast is aligned with the useful part of the Badarinath-style research design:

- a simpler reference configuration versus a more flexible future configuration;
- staged implementation and benchmark logic;
- focus on what flexibility changes operationally and economically.

But this thesis does not copy Badarinath's main emphasis on bidding-strategy variation. The steel freeze is instead designed to support later comparison of:

- forecast and scenario inputs;
- market participation stages;
- realised flexibility value under a fixed credible plant topology.

## Why D-Only Versus D+4 Is Not Part Of This Freeze

`D_only` versus `D_plus_4` is a later operational experiment-design question, not a plant-configuration question.

The future model may use rolling lookahead, possibly `D_plus_4` or a longer window, but this scope freeze does not create horizon-comparison artifacts and does not reopen the thesis around forecast-horizon comparison inside the steel configuration layer.

That comparison remains outside `S2.5e`.
