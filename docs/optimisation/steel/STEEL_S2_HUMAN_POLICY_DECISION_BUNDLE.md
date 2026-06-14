# Steel S2 Human Policy Decision Bundle

## Purpose And Scope

This memo records the current human modelling-policy decisions for deterministic `S2`.

It exists so later Codex tasks can apply the same policy bundle consistently without repeated review loops.

This memo records policy, convention, and sensitivity-strategy decisions only. It does not approve exact numerical plant parameters.

## Status Boundary

This is a human decision record, not a Codex approval artifact.

Approved-input tables remain empty after this task.

The bundle does not populate `s2_approved_model_input`, does not populate the promotion decision template, and does not create executable `S2` rows.

## Endpoint Policy Decision

- `CYC50` is the deterministic `S2` base-case endpoint-neutrality policy.
- Initial inventory equals `50%` of the later approved store capacity.
- Terminal inventory equals beginning inventory.
- Inventory states are non-negative tonnes of the relevant carrier.
- This is a methodological anti-gaming rule.
- This is not Tata operational truth.
- This does not approve any buffer capacity.

## Buffer Classification Decision

### Main Credible Flexibility Buffers

- `HDRI/DRI` surge buffer is the main short-term `DRP-EAF` decoupling buffer.
- cold slab or slab-`WIP` yard is the downstream medium-term decoupling buffer.

### Secondary Or Synchronisation Buffers

- hot metal buffer is a small `BF-BOF` synchronisation buffer only.
- hot slab `WIP` is a thermally constrained transfer or `WIP` buffer, not a strategic flexibility asset.

### Feasibility-Only Or Omitted Buffers

- liquid steel, ladle, tundish, and hot transfer buffers should be omitted or treated as tiny feasibility-only buffers.

### Excluded From S2 Base-Case Flexibility

- coke stock
- sinter stock
- pellet stock
- finished goods and order-book inventory

### Interpretation Note

Hot slab `WIP` must not be treated as a multi-hour or multi-day arbitrage buffer.

Cold slab yard or slab-`WIP` is the actual downstream flexibility buffer.

## Buffer Sizing-Basis Decision

- heats may be used only as relative sizing units for short-term batch-coupling buffers
- `BOF` heats are the relative sizing basis for hot metal synchronisation
- `EAF` heats are the relative sizing basis for `HDRI/DRI` surge
- days of throughput may be used for medium-term stores such as cold slab yard or optional `CDRI/HBI` storage
- exact capacities in tonnes are not approved here
- later capacity rows may only be recorded as assumption-backed base or sensitivity values after explicit review

## Conversion-Coefficient Convention Decision

- use positive magnitudes with explicit role fields rather than signed coefficients
- required minimum role taxonomy:
  - `input_consumption`
  - `output_production`
  - `yield`
  - `share`
  - `loss`
- unit basis should be carrier per activity, for example `t_input/t_activity` or `t_output/t_activity`
- default activity basis should be process output unless explicitly reviewed otherwise
- recipe-style coefficients and yield-style coefficients must remain distinct
- validation coefficients must remain separate from executable coefficients

## Process-Bound Policy Decision

- future executable process bounds should use positive `t/h` magnitudes
- annual public values remain validation or scaling anchors until annual-to-hourly translation is explicitly reviewed
- `BF` is near-must-run or continuous and should not be given free hourly start-stop flexibility
- `DRP` is continuous with possible turndown and should not be given free on-off cycling
- `BOF` and `EAF` are batch-equivalent hourly assets rather than perfect dimmers
- casting and `HSM` or downstream are bounded process or sink layers rather than primary flexibility assets
- coke, sinter, and pellet processes are near-must-run or exogenous or throughput-bounded in `S2`, not dispatch-flex assets

## Production Target Policy Decision

- deterministic `S2` should use a fixed horizon-total fulfilment policy
- target basis must use one approved sink or carrier basis
- no route-specific production target should be imposed in the base case
- route shares are validation or sensitivity information only
- public annual production or planning anchors remain validation or scaling evidence until explicit annual-to-horizon translation is approved
- if shortfall is ever allowed later it must be explicit and reported
- hidden infeasibility penalties are not allowed

## Sensitivity Strategy Decision

- early sensitivities are for debugging and assumption screening only
- early screening should focus on high-impact assumptions:
  - `DRI/HDRI` surge size
  - cold slab or `WIP` yard size
  - `DRP` turndown
  - `BF` near-must-run band
  - production target level or basis
- final thesis sensitivity runs should include only assumptions that materially affect feasibility, flexibility value, production fulfilment, or validation credibility
- store capacities remain high risk and must be reviewed carefully before final thesis use

## What Remains Undecided

- exact store capacities in tonnes
- exact process bounds
- exact conversion coefficient values
- exact production target scale
- exact annual-to-hourly translation methods
- exact `DRP` turndown band
- exact `BF` near-must-run band
- exact `BOF/EAF` batch-equivalent hourly capacity treatment
- final validation-target set

## What Is Still Blocked From Executable Use

- all approved-input shell tables remain zero-row
- policy records are non-executable
- convention records are non-executable
- sensitivity-strategy records are non-executable
- no exact numerical value in this memo is approved for thesis-grade or executable use
- annual public anchors still cannot become executable hourly inputs without separate translation review
- validation targets still cannot become live constraints without reclassification and later review

## How Future Codex Tasks Should Use This Bundle

- treat the bundle as the current human policy baseline for deterministic `S2`
- use it to keep future review packets, schema decisions, and candidate-review interpretation aligned
- do not convert this bundle directly into approved-input rows
- do not infer exact capacities, coefficients, bounds, or targets from these policy statements
- when later tasks need exact numerical inputs, require separate review and explicit promotion or later executable gating

## Why This Does Not Approve Exact Numerical Values

The bundle records methodological choices, classification logic, and convention choices.

Those choices constrain how later parameters should be reviewed, but they do not supply approved exact numerical plant values.

Human policy selection is therefore separate from numerical promotion, thesis-grade numerical approval, and executable-use approval.
