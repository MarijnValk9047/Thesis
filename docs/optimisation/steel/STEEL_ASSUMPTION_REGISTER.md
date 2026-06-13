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
| `A_SOURCE_HIERARCHY_001` | Where simplified Tata explainer pages conflict with the later MER technical description, MER Deel B controls the default Wave B topology reading. | `frozen_for_phase` | `S03` versus simplified web explainers such as `S11` | Prevents repository topology drift toward legacy or simplified wording that conflicts with the technical EIA. | Required | Public explainer text is not allowed to override the technical MER in thesis-facing topology definitions. |
| `A_PHASE1_CLOSURE_PAIR_001` | The default Phase 1 closure pair is BF7 plus KGF2, based on the best current public reading of the Green Steel / Heracless configuration. | `frozen_for_phase` | `S02`; `S03`; `S05` | Determines the default future-case topology and asset availability. | Required | This is the current public default, not a claim of immutable future reality. |
| `A_KGF1_PHASE1_001` | KGF1 is retained in the default Phase 1 hybrid case unless a separate exogenous early-closure scenario is activated. | `frozen_for_phase` | `S03`; `S05` | Affects coke and gas availability and prevents accidentally removing both coke plants from the default future case. | Required | Default Phase 1 keeps KGF1; removing it requires an explicit scenario flag and caveat. |
| `A_EARLY_COKE_CLOSURE_001` | Earlier closure of KGF1 and KGF2 is treated as an exogenous regulatory or permit-risk scenario only, not as the default Phase 1 topology. | `provisional` | `S16` | Preserves separation between the current public default topology and a later permit-driven alternative. | Required | Early-coke-closure results must be labelled scenario-specific and not presented as the base case. |
| `A_PUBLIC_ANNUAL_VALUES_001` | Public annual or planning values are used as validation targets or candidate ranges, not as exact hourly dispatch constraints. | `frozen_for_phase` | `S03`; `S04`; `S06`; Wave B memo governance rule | Prevents false precision in hourly optimisation and protects annual validation logic from being misused as operating truth. | Required | Public planning numbers are not equivalent to hourly plant capabilities. |
| `A_AVERAGE_POWER_001` | Average MW demand values are validation anchors only and must not be treated as connection capacity, peak demand, or contract capacity. | `frozen_for_phase` | `S03`; Wave B memo red-flag rule | Prevents misuse of annual-average power figures in grid-capacity constraints. | Required | Average MW demand is not connection capacity. |
| `A_RECIPES_AND_QUALITY_001` | Exact public Tata recipes, yields, and quality windows are not available at the fidelity needed for direct model use and remain assumption or sensitivity material for later waves. | `provisional` | Wave B memo assumptions table | Blocks premature promotion of route recipes and quality windows into approved model inputs. | Required | Early steel results must state that recipes, yields, and quality logic remain simplified. |
| `A_ETS_WAG_VALUATION_001` | ETS/free-allocation treatment and internal WAG valuation remain later evidence tasks and must not be frozen from high-level public narrative alone. | `provisional` | Wave B memo assumptions table; `S12`; `S03` | Can materially affect route economics, cost attribution, and later risk claims. | Required | Carbon-cost and internal-gas-value choices must remain explicit, source-backed, and caveated before thesis use. |
| `A_ANNUAL_TO_HOURLY_001` | Annual public values may only be translated into hourly candidate envelopes through explicit availability and utilisation assumptions that remain visible and reviewable. | `frozen_for_phase` | Wave C methodology rule | Prevents hidden conversion of annual planning values into false hourly truth. | Required | Annual-to-hourly translation is methodology, not observed operating evidence. |
| `A_BF_DRP_CONTINUITY_001` | BF and DRP are treated as continuity-driven assets in S2 and therefore use narrow hourly envelopes rather than free wide turndown behaviour. | `frozen_for_phase` | Wave C generic technology framing | Shapes the first material-flow LP so continuity-driven assets are not misrepresented as highly flexible. | Required | Continuity-driven treatment is an S2 modelling simplification, not a detailed operating rulebook. |
| `A_BOF_EAF_BATCH_001` | BOF and EAF are treated as batch-equivalent assets in S2 rather than as fully continuous free dimmers. | `frozen_for_phase` | Wave C generic technology framing | Avoids false flexibility and preserves the physical distinction between continuity-driven and heat-based processes. | Required | S2 hourly representation is an annualised approximation with explicit batch caveats. |
| `A_EAF_NOT_DIMMER_001` | The EAF must not be represented in S2 as a continuously variable free dimmer without explicit batch-equivalent logic and feed constraints. | `frozen_for_phase` | Wave C modelling rule | Prevents artificial dispatch smoothness and exaggerated intrahour flexibility. | Required | Any coarse hourly EAF logic must state that it is batch-equivalent only. |
| `A_HDRI_SHORT_TRANSFER_001` | HDRI is represented as short local transfer only and not as a long-duration storage medium. | `frozen_for_phase` | Wave C generic DRI product-class evidence | Prevents the creation of unrealistic storage flexibility around hot DRI. | Required | HDRI transfer freedom must stay physically tight and short-lived. |
| `A_CDRI_HBI_STORAGE_001` | CDRI or HBI may be treated as storage-like only with explicit physical caveats such as throughput, safety, oxidation, and endpoint treatment. | `provisional` | Wave C generic DRI product-class evidence | Allows colder DRI forms to be represented more flexibly without implying frictionless storage. | Required | Storage-like does not mean battery-like. |
| `A_SLAB_WIP_NOT_BATTERY_001` | Slab or WIP inventory is not a free battery and requires terminal rules and, where relevant, reheating, loss, or penalty logic. | `frozen_for_phase` | Wave C downstream route evidence | Prevents the downstream route from absorbing inconsistencies through unconstrained stock shifts. | Required | Slab or WIP buffering must be disclosed as physically constrained and value-relevant. |
| `A_HOT_COLD_ROUTE_001` | Downstream hot-route versus cold-route treatment is represented explicitly when relevant rather than hidden inside a generic slab inventory pool. | `provisional` | Wave C hot-charging and reheating evidence | Affects downstream energy, timing, and possible quality-loss proxies once those layers are opened. | Recommended | If omitted in early phases, the simplification must be stated explicitly. |
| `A_TURNDOWN_SENSITIVITY_001` | Exact turndown ranges for BF, DRP, BOF, and EAF remain sensitivity-only until stronger evidence supports a phase-specific approved envelope. | `provisional` | Wave C generic technology ranges | Prevents overclaiming process flexibility from generic literature ranges alone. | Required | Range choices must stay labelled as candidate or sensitivity material. |
| `A_TATA_RECIPES_NOT_APPROVED_001` | Exact Tata recipes and yields remain not approved even after Wave C, because generic technology ranges do not replace site-specific evidence. | `frozen_for_phase` | Wave C governance rule | Keeps generic range evidence separate from approved Tata-like operating inputs. | Required | Wave C provides candidate technology ranges, not approved site recipes. |
| `A_NO_CONFIDENTIAL_TRANSFER_PRICES_001` | Minimal S3 does not use confidential or guessed Tata or Vattenfall internal transfer prices. | `frozen_for_phase` | Wave D governance rule; `WD02`; `WD03` | Blocks hidden internal-price assumptions from entering the first steel cost layer. | Required | Internal-energy valuation remains public and auditable rather than contract-driven. |
| `A_VATTENFALL_INTERFACE_001` | In minimal S3, Vattenfall is modelled as an exogenous interface rather than as a fully dispatched plant model. | `frozen_for_phase` | `WD02`; `WD03`; `WD05`; `WD06` | Defines the S3 boundary and prevents premature detailed utility dispatch claims. | Required | The first energy layer does not represent full Vattenfall unit commitment or confidential operating rules. |
| `A_WAG_VALUE_PATH_001` | WAGs receive value only through explicit useful-energy substitution, especially natural-gas replacement, and through a non-zero flare or spill penalty where relevant. | `frozen_for_phase` | `WD01`; `WD09`; `WD10`; `WD14` | Prevents hidden free-energy revenue and preserves physical valuation logic. | Required | WAG value is structural and caveated, not a hidden revenue credit. |
| `A_NO_DIRECT_ELECTRICITY_PRICE_WAG_001` | WAGs are not valued directly at electricity-market price unless an explicit reviewed conversion path is later modelled. | `frozen_for_phase` | Wave D valuation rule; `WD09`; `WD10` | Prevents free arbitrage and exaggerated WAG value. | Required | Direct electricity-price valuation of WAGs is forbidden in the minimal S3 scaffold. |
| `A_NONZERO_FLARE_PENALTY_001` | Every minimal S3 formulation with WAG carriers requires a non-zero flare or spill penalty. | `frozen_for_phase` | Wave D red-flag rule; `WD01`; `WD09`; `WD10` | Stops the model from treating waste-gas disposal as frictionless. | Required | Penalty magnitude may remain candidate material, but zero is not allowed. |
| `A_BOF_HOLDER_UNKNOWN_001` | The BOF or oxygas holder exists as public structure, but its capacity remains unknown unless stronger stable public evidence is added. | `provisional` | `WD02`; `WD01` | Allows simple holder structure while blocking invented Tata-specific capacities. | Recommended | Holder logic may be present before holder capacity is approved. |
| `A_MIXED_GAS_SETPOINT_UNKNOWN_001` | Mixed-gas setpoints and calorific-control logic remain under-specified publicly and are postponed from minimal S3. | `frozen_for_phase` | `WD07`; `WD08`; `WD09` | Keeps the first energy layer tractable and avoids false precision in gas-mixing constraints. | Recommended | Minimal S3 is carrier-specific without full mixed-gas optimisation. |
| `A_WAG_CARBON_NO_DOUBLE_COUNT_001` | WAG carbon accounting must use one consistent architecture that avoids counting the same carbon at generation and again at later combustion or flare. | `frozen_for_phase` | `WD11`; `WD12`; `WD14` | Protects emissions reporting and later ETS framing from systematic overstatement. | Required | WAG emissions architecture must be disclosed before thesis use. |
| `A_DERIVED_WAG_EF_SENSITIVITY_001` | Derived WAG emissions factors from public composition and LHV logic remain sensitivity-only unless a stronger approved convention is frozen. | `provisional` | Wave D candidate layer; `WD01`; `WD12`; `WD15`; `WD16` | Prevents derived coefficients from being promoted silently into approved inputs. | Required | Derived WAG emissions factors are not approved operating constants. |
| `A_ETS_FREE_ALLOC_POSTPONED_001` | ETS and free-allocation detail remain postponed beyond minimal S3. | `frozen_for_phase` | `WD11`; `WD12`; `WD13` | Keeps the first cost and emissions layer from overstating policy precision. | Required | Any ETS treatment before Wave E is only gross-cost or placeholder framing. |
| `A_STEAM_OXYGEN_UTILITIES_POSTPONED_001` | Detailed steam, oxygen, and wider utility-network scheduling remain postponed from minimal S3. | `frozen_for_phase` | `WD02`; `WD07`; `WD08` | Preserves tractability and avoids building a false full-utility digital twin from incomplete public data. | Recommended | Minimal S3 is a WAG-focused semi-detailed layer, not a full utility model. |

## Use Rules

1. If an implementation choice depends on one of these items, the related assumption must be updated first.
2. If an assumption materially affects route economics or flexibility, it requires a sensitivity decision before thesis use.
3. If a public source and a prior thesis disagree, record both and freeze a modelling assumption explicitly.
4. If an assumption is still `open`, do not present resulting outputs as plant-representative evidence.
5. If a public annual or average planning value is reused in model design, explicitly tag it as `validation target`, `candidate range`, or `assumption`, never as hidden hourly truth.

## Minimum Reporting Rule

Every future steel run should be able to list:

- which assumptions were frozen;
- which remained provisional;
- which were tested in sensitivity;
- which assumptions block thesis-grade interpretation.
