# Steel S2 Minimal Numerical Policy Decision Bundle

## Purpose And Scope

This memo records the current human numerical-policy decisions for the first deterministic `S2` development surface.

It records human numerical-policy decisions so later development-only `S2` tasks do not need to reopen the same baseline choices.

It exists to freeze the minimum non-thesis numerical-policy structure needed for later development-only deterministic `S2` LP scaffolding.

This memo records human decisions, provisional structures, and screening priorities only. It does not approve exact numerical values.

## Status Boundary

This is a human numerical-policy decision record, not a Codex approval artifact.

s2_approved_model_input remains empty after this task.

The new provisional development pack is development-only and not thesis-usable.

This bundle does not populate approved-input tables, does not populate the promotion decision template, and does not create thesis-usable executable rows.

## Process-Bounds And Annual-To-Hourly Translation Policy

- annual public anchors are not direct hourly caps
- future process bounds must use positive `t/h` values
- hourly process bounds require explicit effective-hours, availability, utilisation, or batch-equivalent translation
- `BF` and `DRP` are continuous-envelope assets
- `BF` is near-must-run and continuous with no free hourly start-stop flexibility
- `DRP` is continuous with possible turndown and no free on-off cycling
- `BOF` and `EAF` are batch-equivalent hourly assets
- casting and `HSM` or downstream are bounded process or sink layers, not primary flexibility assets
- conservative, central, and flexible envelopes may later be reviewed as scenarios rather than treated as one exact truth
- the first deterministic LP may use provisional base envelopes for development only, but thesis use still requires later validation and sensitivity review

## Buffer-Capacity Treatment

- `HDRI/DRI` surge is included as the main short-term flexibility buffer
- `HDRI/DRI` surge should be sized relative to `EAF` heat equivalents
- provisional base structure is around one `EAF` heat equivalent
- provisional sensitivity structure may later compare smaller or no surge against larger `2` to `4` heat-equivalent cases
- cold slab or slab-`WIP` yard is included as the main downstream medium-term flexibility buffer
- cold slab or slab-`WIP` should be sized relative to days of downstream throughput
- provisional base structure is around `1` to `2` days of downstream throughput
- provisional sensitivity structure may later compare constrained `0.5` day against flexible `3` to `7` day cases
- hot metal is included only as small synchronisation, not strategic market flexibility
- hot metal should be sized relative to `BOF` heat equivalents or a narrow hour-equivalent feed basis
- hot slab `WIP` is omitted in the base case unless topology continuity later requires a tiny thermal-transfer treatment
- hot slab `WIP` must not be treated as a strategic multi-hour or multi-day flexibility store
- liquid steel, ladle, tundish, and hot transfer buffers are omitted or tiny feasibility-only
- coke, sinter, pellet, finished-goods, and order-book inventories remain excluded from `S2` base-case flexibility
- `CYC50` remains endpoint policy only and does not approve any buffer capacity

## Production-Target Basis And Translation Policy

- deterministic `S2` uses one fixed horizon-total fulfilment target
- target basis should be the last modelled metallic sink unless explicitly reviewed otherwise
- no route-specific base targets are imposed
- route-specific anchors or route shares remain validation or sensitivity information only
- annual public production or planning anchors remain validation or scaling evidence until explicit annual-to-horizon translation is reviewed
- one-day runs remain debugging only
- one-week runs are the first serious physical-interpretation horizon
- shortfall must not be hidden behind penalties
- if shortfall is ever allowed later it must be explicit and reported

## Early Sensitivity-Screening Strategy

- early sensitivities are for debugging and assumption screening, not final thesis conclusions
- early screening should be one-at-a-time or otherwise minimal rather than full factorial
- first screening priorities are:
  - `HDRI/DRI` surge size
  - cold slab or slab-`WIP` capacity
  - `DRP` turndown
  - `BF` near-must-run band
  - production target level or basis
- final thesis sensitivities should later be selected by materiality:
  - feasibility
  - flexibility value
  - production fulfilment
  - validation credibility
  - computational impact
- store capacities remain high risk and must stay sensitivity-aware before final thesis use

## What Remains Undecided

- exact store capacities in tonnes
- exact hourly process bounds in `t/h`
- exact conversion coefficient values
- exact production target quantities
- exact annual-to-hourly translation parameters
- exact annual-to-horizon target translation method
- exact `BF` near-must-run band
- exact `DRP` turndown band
- exact `BOF` and `EAF` hourly-equivalent capacities

## What Is Still Blocked From Thesis Or Executable Use

- `s2_approved_model_input` remains zero-row
- the provisional dev pack is not thesis-usable
- annual public anchors still cannot become hourly caps without separate translation review
- route-specific annual anchors still cannot become base production constraints
- validation targets still cannot become live constraints
- provisional structures still cannot be cited as thesis-grade exact values
- no deterministic `S2` LP builder or solver-ready input surface is created here

## Why Provisional Base And Sensitivity Structures Are Not Thesis-Grade Exact Values

The provisional structures record development choices such as heat-equivalent or days-of-throughput bases.

Those structures are useful for later smoke-test scaffolding, but they are not approved plant quantities, not reviewed hourly caps, and not thesis-grade target quantities.

Development-only base or sensitivity structure is therefore separate from thesis-grade numerical approval.

## How Future Codex Tasks Should Use This Bundle

- treat this memo as the current human numerical-policy baseline for development-only deterministic `S2`
- use it to scaffold non-thesis provisional inputs without populating `s2_approved_model_input`
- keep future development prompts explicit about `thesis_usability=false`
- refuse to convert annual anchors directly into hourly caps or route-specific base constraints
- require later review before any provisional row is reused as thesis-grade or approved input

## Why This Does Not Approve Exact Numerical Values

This bundle records policy, translation requirements, provisional structures, and screening priorities.

It does not approve exact tonnes, exact `t/h`, exact coefficients, exact target quantities, costs, tariffs, emissions factors, bid quantities, or market prices.

Exact numerical approval remains a separate later governance step.
