# Steel Assumption Register

## Goal

Record the uncertain, disputed, simplified, or policy-driven assumptions that the steel model will need before coding begins.

Public sources, prior theses, and public transition material may disagree, may be redacted, or may describe different planning vintages. Those items must appear as assumptions or sensitivity cases, not as hidden facts.

## Status Labels

Use these labels unless a later schema freezes a different controlled vocabulary:

- `open`
- `provisional`
- `frozen_for_phase`
- `sensitivity_required`
- `retired`

## Register Fields

Each assumption entry should carry:

| Field | Purpose |
|---|---|
| `assumption_id` | Stable identifier |
| `assumption_statement` | Plain-language statement |
| `current_status` | Open, provisional, frozen_for_phase, sensitivity_required, or retired |
| `source_or_evidence` | Placeholder for source card, note, or supporting citation |
| `model_impact` | What changes if this assumption changes |
| `sensitivity_requirement` | None, recommended, or required |
| `thesis_reporting_caveat` | How the limitation must be disclosed |

## Initial Register

| Assumption ID | Assumption Statement | Current Status | Source Or Evidence | Model Impact | Sensitivity Requirement | Thesis Reporting Caveat |
|---|---|---|---|---|---|---|
| `A_SITE_BOUNDARY_001` | The first steel model uses a bounded site representation that includes only the process units and carriers needed for DA flexibility analysis, not a full plant balance for every utility and downstream finishing asset. | `provisional` | Placeholder | Determines what flows must balance internally and which exogenous imports/exports are allowed. | Required | Results apply to the defined model boundary only, not to the entire site. |
| `A_TARGET_POLICY_001` | Production is represented through a tractable target policy such as daily slab, hot-metal-equivalent, or steel-output targets rather than a full order-book model. | `provisional` | Placeholder | Strongly affects route utilisation, flexibility, and reported economics. | Required | Profit results are conditional on the chosen production-policy abstraction. |
| `A_BFBOF_RIGIDITY_001` | The current BF-BOF route is modelled as operationally rigid relative to the future hybrid route, but not completely inflexible. | `provisional` | Placeholder | Sets the baseline level of load shifting and benchmark comparison. | Required | Avoid claims that the baseline is fully inflexible unless a source supports that. |
| `A_PHASE1_DEF_001` | The main future case is a Phase 1 hybrid BF-BOF + DRP-EAF configuration with an explicit route definition frozen before forecast comparison experiments. | `provisional` | Placeholder | Defines which units, carriers, and buffers exist in the main case. | Required | Forecast comparisons are invalid if the Phase 1 definition shifts between runs. |
| `A_BF7_COKE_001` | BF7 and coke-plant closure timing, residual operation, or replacement interactions may be ambiguous across public sources and must not be treated as settled site truth without explicit evidence. | `open` | Placeholder | Affects baseline topology, emissions, and asset availability. | Required | Conflicting public narratives must be disclosed rather than resolved silently. |
| `A_DRI_BUFFER_001` | DRI buffer behaviour is initially represented as an aggregated storage or staging buffer with explicit capacity and throughput assumptions, not as a hidden unlimited inventory pool. | `provisional` | Placeholder | Strongly affects route decoupling and apparent flexibility. | Required | Any DRI inventory abstraction can create artificial flexibility if underconstrained. |
| `A_EAF_FLEX_001` | EAF flexibility is represented with explicit min/max load and ramping logic, and only later extended to richer thermal or batch logic if needed. | `provisional` | Placeholder | Controls the main electrical flexibility signal in the hybrid route. | Required | Early results reflect a simplified EAF flexibility model, not a full operating rulebook. |
| `A_SLAB_REHEAT_001` | Slab yard, hot charging, and reheating are initially simplified into aggregated downstream demand or buffer logic rather than a detailed finishing-line model. | `provisional` | Placeholder | Affects temporal coupling between upstream steelmaking and downstream delivery. | Recommended | Downstream simplification may mute or exaggerate true flexibility windows. |
| `A_WAGS_001` | Waste and process gases are initially aggregated unless later evidence shows a detailed gas-network representation is necessary for credible flexibility or emissions results. | `provisional` | Placeholder | Affects energy balances, internal fuel substitution, and route economics. | Required | Aggregated WAG treatment is a methodological simplification, not site truth. |
| `A_ETS_001` | ETS is modelled through an explicit convention that must be frozen per experiment: gross cost, avoided-cost framing, and any surplus-sale sensitivity must be separated. | `provisional` | Placeholder | Can materially change route ranking and reported economics. | Required | ETS treatment must be stated in every steel result summary. |
| `A_RESIDUAL_LOADS_001` | Residual non-modelled loads are handled through an explicit residual-load term or exogenous demand policy rather than silently ignored. | `open` | Placeholder | Determines total site electricity exposure and DA procurement scale. | Required | Ignoring residual loads can overstate the value of flexible units. |
| `A_CONFIDENTIALITY_001` | Confidential, redacted, or unclear plant values are represented as assumptions, ranges, or sensitivity cases, never as precise hidden constants. | `frozen_for_phase` | Governance rule | Affects data integrity across the full model. | Required | Public/redacted data are not exact site truth and must be described that way. |

## Use Rules

1. If an implementation choice depends on one of these items, the related assumption must be updated first.
2. If an assumption materially affects route economics or flexibility, it requires a sensitivity decision before thesis use.
3. If a public source and a prior thesis disagree, record both and freeze a modelling assumption explicitly.
4. If an assumption is still `open`, do not present resulting outputs as plant-representative evidence.

## Minimum Reporting Rule

Every future steel run should be able to list:

- which assumptions were frozen;
- which remained provisional;
- which were tested in sensitivity;
- which assumptions block thesis-grade interpretation.
