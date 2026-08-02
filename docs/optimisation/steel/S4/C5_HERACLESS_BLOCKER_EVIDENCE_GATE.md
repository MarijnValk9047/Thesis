# C5 HERACLES Blocker-Resolution Evidence Gate

## Gate decision

Decision: `evidence_gate_complete_model_freeze_not_yet_reached`.

The 124-page *MER Heracless - Deel B - Technische beschrijving* materially narrows several C5 blockers. It directly resolves what the published 85%/15% generator statement means, supports bounded later tests for DRI/EAF operating states and availability, validates the split DRI energy intensities, and establishes steam and oxygas-holder topology. It does not provide the hourly source-to-sink gas ledger, VN25 minimum-fuel rate, real HSM mixture timescale, usable oxygas-store energy, BF6/BF7 denominators, or terminal-aware held-out evidence needed to freeze the current model.

This is an evidence gate only. It changes no model logic, config, approved input, solver output or optimisation result. Every new register row is non-executable and requires a separate reviewed implementation gate.

## Starting state

The user-authorized HSM controller is retained unchanged:

- a 24-hour block uses COG/NG volume shares of 55%/45% in C0 and 20%/80% in C1, corresponding to 62.384% and 89.021% NG on the configured energy basis;
- BFG and BOFG are excluded from HSM fuel;
- explicit HSM NG displaces the C0 anonymous NG component hourly;
- February and July rolling validation passed 28/28 models;
- the released WAG appears as additional generator use or flare, while WAG production remains approximately 57.352 PJ/y.

HERACLES supports the COG-decline/NG-increase direction at WBW2. The QRA separately supplies design-flow mixture shares. Neither source establishes 24 hours as the real burner-control or allocation timescale. The block length therefore remains a transparent development abstraction, not a source fact.

## Document identity and method

| Field | Verified value |
| --- | --- |
| Cover title | *MER Heracless - Groen Staal; Deel B - Technische beschrijving* |
| Organisation | Tata Steel Nederland / Royal HaskoningDHV |
| Reference and edition | `BI3580-MER`; definitive; 15 September 2025 |
| Official URL | `https://www.tatasteelnederland.com/sites/default/files/mer-groen-staal-deel-b-technische-beschrijving.pdf` |
| PDF length | 124 pages |
| SHA-256 | `8A7A358183234E0B0C5D77588020DD58DC8F8FD20036954CB7004149C6EFB455` |
| Page mapping | PDF page 1 is the cover; PDF page 2 is report page 1; thereafter PDF page = report page + 1 |

All 124 pages were text-extracted and screened. Relevant tables, figures, arrows, captions, footnotes and units were visually checked in the current energy system, Phase-1 volume/energy, energy-central, oxygas-holder, transition, DRI, EAF, partner and special-operation sections. The PDF metadata title says `Samenvattend Hoofdrapport`, but the cover and document-information page identify this file as the definitive technical Part B; the verified hash and report reference remove that ambiguity.

Evidence classes used below:

1. `direct source statement`: a statement or value printed by the report;
2. `transparent calculation`: arithmetic shown from direct source values;
3. `modelling interpretation`: a bounded implication that still needs a reviewed implementation decision;
4. `unsupported inference`: a conclusion the report cannot support.

## Blocker matrix

| ID | Freeze or anchor blocker | Outcome | What HERACLES establishes | Evidence still required / resolving source |
| --- | --- | --- | --- | --- |
| B01 | Meaning of VN25 85% / IJM-01 15% | `directly_resolved` | It is time in operation in the Heracless configuration; VN24 backs up when both are unavailable. | None for meaning. A dispatch rule still requires B02 evidence. |
| B02 | VN25 minimum fuel and generator dispatch | `supports_bounded_implementation_test` | VN25 is primary on available production gases; NG tops up an unspecified minimum fuel need; IJM-01 is standby. | VN25 technical minimum fuel/heat input, efficiency curve, capacities, ramp/start/outage logic and Vattenfall/Tata operating or contract data. |
| B03 | Aggregate 54-PJ WAG recovery anchor | `supports_annual_reporting_only` | Current WAG recovery as heat/electricity is approximately 54 PJ/y across Tata and Vattenfall. | Carrier-separated energy basis and source-to-sink measurement if it is to become more than annual context. |
| B04 | Post-HSM WAG surplus: generator use versus flare | `not_found_in_heracless` | Gas allocation, holder buffering, generator use and flare are physically distinct sinks, but no compatible hourly or annual allocation table explains the model surplus. | ENB/ECC carrier-specific hourly production, process use, generator delivery, holder level and flare meters with common timestamps and LHV basis. |
| B05 | DRI/EAF transition operating envelope | `supports_bounded_implementation_test` | Transition ceiling is 25 kt liquid steel/day; BF and DRI lower levels are around 50% of maximum; bypass and coordinated ramp-up are described. | Commissioning/transition schedule, named capacity denominators and confirmation that each limit is transition-only before any state constraints are implemented. |
| B06 | Normal DRI/EAF availability and decoupling | `supports_bounded_implementation_test` | One DRI maintenance day/month, EAF eight hours/week, 21/14-day annual outages, coordinated stops and cold-DRI decoupling are stated. | Actual outage distributions, overlap rules, cold-DRI usable capacity/initial/terminal state and any production loss during retained warm-hold operation. |
| B07 | DRI energy total and components | `supports_validation_only` | 8.1 GJ/t DRI reduction NG, 1.8 GJ/t DRI furnace NG and 0.3 GJ/t DRI electricity are separate direct values. | Confirmation of NG LHV/HHV basis and exact boundary. They validate but do not automatically replace the existing input. |
| B08 | Steam topology and startup/short-stop demand | `supports_topology_only` | DRI top-gas heat recovery supplies internal steam; startup initially needs about 50 t/h external steam; short stops need external steam; EAF heat recovery supplies vacuum-ladle treatment. | Header topology, pressure, temperature/enthalpy, flow profiles, condensate return and simultaneous consumer/supplier data for a complete balance. |
| B09 | Oxygas-holder energy storage | `supports_topology_only` | A new 83,400-m3 holder buffers batch oxygas to steady consumers. | Usable working volume, gas composition, pressure range, temperature convention, LHV and operating bounds. |
| B10 | HSM/WBW fuel direction | `supports_topology_only` | WBW2 needs more NG as COG availability declines. | Burner-level demand, fuel hierarchy, mixture feasibility, limits and time-series operating data. QRA design shares remain a separate development source. |
| B11 | Real HSM mixture timescale | `not_found_in_heracless` | No switching, blending or burner-control timescale is stated. | HSM/WBW control specification or historian data. The implemented 24-hour block remains user-authorized abstraction. |
| B12 | Electricity residual and import anchor | `supports_annual_reporting_only` | The report states annual current and Heracless electricity generation/import totals and average site power demand. | Interval-metered boundary imports, self-generation and consumer categories on a compatible configuration and loss basis. |
| B13 | Coal/coke definition mismatch | `conflicting_evidence_requires_adjudication` | Phase-1 coal is stated as both about 2.2 Mt/y and 58 PJ/y, while the report does not reconcile these definitions with the model's coke/coal boundary. | MER calculation workbook or methodology defining coal, coking coal, coke, anthracite, moisture and energy basis; retain the 58-PJ energy comparison meanwhile. |
| B14 | BF6/BF7 comparability | `not_found_in_heracless` | The report gives transition totals and approximate minima, not separate comparable production and nameplate denominators. | Asset-specific BF6/BF7 output, burden and capacity data over the same period/configuration. |
| B15 | Full carrier-specific WAG allocation | `not_found_in_heracless` | BFG, COG and BOFG remain physically distinct in the prose, but no complete allocation table closes production to every process, generator, holder and flare. | Carrier-specific source-to-sink mass/volume/energy ledger with gas quality and common time basis. |
| B16 | Frozen terminal-aware held-out validation | `cannot_be_resolved_from_this_document_type` | Nothing: a document review cannot test recursive feasibility or terminal-state behavior. | Execute the separately frozen held-out dynamic protocol against the unchanged accepted model. |

## Page-verifiable findings

| ID | Class | Report / PDF locator | Finding and boundary |
| --- | --- | --- | --- |
| F01 | direct source statement | p.23 / PDF 24; 3.6.1 | ENB/ECC distribute steam, electricity and the separate production gases to Tata and Vattenfall users. This is topology, not an allocation schedule. |
| F02 | direct source statement | p.32 / PDF 33; 4.3 | About 54 PJ/y is recovered as WAG heat/electricity; Vattenfall may add NG; grid import is about 1 PJ/y. All are annual current-system context. |
| F03 | direct source statement | pp.48 and 115 / PDF 49 and 116; 5.3 and 14.5 | VN25 85% and IJM-01 15% are operating-time assumptions. VN25 is primary on available production gases, NG supplies the minimum-fuel shortfall, and IJM-01/VN24 are backups. No output split or minimum rate is printed. |
| F04 | direct source statement | p.49 / PDF 50; Tables 5.1-5.2 | Phase-1 annual factory/route volumes and flexibility are planning bases. Footnotes say volumes are rounded to 0.1 Mt and percentages use unrounded volumes. |
| F05 | direct source statement | p.51 / PDF 52; 5.5 | Heracless annual energy shifts from coal toward NG and grid electricity. These totals do not give dispatch or source-to-sink WAG allocation. |
| F06 | direct source statement | pp.70-71 / PDF 71-72; 7.4 | BOFG arrives in batches, the holder feeds steadier consumers, and geometric capacity is 83,400 m3. Usable energy is not reported. |
| F07 | direct source statement | pp.82 and 85 / PDF 83 and 86; 9.3 and 9.7 | DRI can run in bypass with no output while process gas circulates and the furnace stays hot. The 50% minima and 25-kt/day ceiling are explicitly discussed in commissioning/transition context. |
| F08 | direct source statement | p.87 / PDF 88; 10.2 | DRI top-gas heat recovery makes steam used within the DRI plant. It is not evidence of site-wide export capacity. |
| F09 | direct source statement | p.89 / PDF 90; 10.3 | The DRI furnace burns tailgas with NG and later H2; absent alternative use, tailgas would need to be flared. This does not quantify a normal flare flow. |
| F10 | direct source statement | p.92 / PDF 93; 10.6 | DRI uses 8.1 GJ/t reduction NG, 1.8 GJ/t furnace NG and 0.3 GJ/t electricity. The source does not label the gas calorific-value convention. |
| F11 | transparent calculation | p.92 / PDF 93; 10.6 | `8.1 + 1.8 = 9.9 GJ NG/t DRI`. This checks the existing aggregate magnitude while preserving the two physical services and the unresolved LHV/HHV basis. |
| F12 | direct source statement | pp.93 and 120 / PDF 94 and 121; 11.1 and 15.3 | Cold DRI lets EAF continue when DRI stops and lets DRI continue when EAF stops. No usable bunker capacity or duration is given. |
| F13 | direct source statement | p.98 / PDF 99; 11.3 | EAF off-gas heat recovery makes steam for vacuum-ladle treatment. No wider steam export is stated. |
| F14 | direct source statement | p.116 / PDF 117; 14.6 | GOS North supplies more NG to WBW2 because COG use falls. This supports fuel direction, not the QRA shares or a 24-hour block. |
| F15 | direct source statement | pp.118-120 / PDF 119-121; 15.1-15.3 | Startup external steam is initially about 50 t/h and declines; short stops use external steam; recurring and annual outages are stated; cold DRI supports coordination. |
| F16 | modelling interpretation | F03-F06 and current HSM validation | The post-HSM released WAG should remain an allocation/sink question. HERACLES provides no basis to change WAG yields or force agreement with 54 PJ/y. |
| F17 | modelling interpretation | F07 and F12-F15 | A later state-machine/availability sensitivity can test bypass, outages and finite cold-DRI decoupling, but must keep transition and normal-operation rules separate. |
| F18 | unsupported inference | no source locator | Treating 85/15 as generation output, assigning an exact VN25 minimum, converting 83,400 m3 to MWh, assuming startup steam is a site balance, or calling 24 hours the real HSM timescale is unsupported. |

## Conflicts and limitations

- The report's generator configuration is internally clear, but its environmental worst-case discussion can assume both plants at full capacity for heat-discharge assessment. That worst case must not be mistaken for the operating-time configuration or dispatch.
- The transition chapter gives strong state evidence, while normal-operation chapters give continuity and maintenance evidence. Combining the transition 50% minimum with normal recurring availability would over-generalize the source.
- The report separates 8.1 and 1.8 GJ/t DRI but does not state LHV/HHV. The arithmetic matches the existing 9.9-GJ-LHV/t magnitude; energy-basis equivalence remains validation-only.
- The 54-PJ/y WAG context aggregates carriers and heat/electricity sinks. It cannot adjudicate the model's approximately 57.352-PJ/y production total or the post-HSM split between useful generation and flare.
- Published annual electricity and coal values improve reporting, but incompatible boundary/denominator definitions prevent them becoming hourly constraints or physical input corrections.

## Ranked next gates

1. **Frozen held-out dynamic validation.** Run the already defined terminal-aware held-out protocol against the unchanged HSM-enabled model. This is the only direct route to the remaining model-freeze gate and no document finding substitutes for it.
2. **DRI/EAF operating-state and availability test.** In a separate reviewed gate, test transition-only 25-kt/day and approximate 50% limits separately from normal outages; include bypass and finite cold-DRI decoupling with explicit initial/terminal rules. Do not promote without capacity and scheduling adjudication.
3. **Steam topology closure test.** Add only after header conditions and flow evidence exist; test DRI internal recovery, startup decline, short-stop external supply and EAF-to-vacuum-ladle recovery as separate services.
4. **VN25 minimum-fuel test.** Preserve WAG-first/NG-top-up topology, but wait for a source-compatible minimum heat input or MW/efficiency basis. Keep 85/15 as validation context, never output allocation.
5. **Oxygas-holder test.** Implement only after working volume, pressure and gas-quality evidence establish an energy basis and finite terminal contract.

The ranked tests are recommendations, not authorization. This gate stops before any source-backed model change.

## Acceptance checks

- `STEEL-SC-0016` remains the single canonical HERACLES source; no duplicate source was created.
- The existing `STEEL-WAG-EVID-0045` row is refined in place for the 85/15 operating-time meaning.
- All new candidate rows point to `STEEL-SC-0016`; none is approved, executable or eligible for thesis input.
- No personal download path is stored in canonical evidence; only the official URL, report identity and verified hash are retained.
- HSM allocation remains separate from WAG production; the 54-PJ/y context is not a yield-fitting target.
- No annual value is converted into an hourly constraint, and no transition-only rule is made universal.
- Frozen held-out validation remains a separate methodological gate.
