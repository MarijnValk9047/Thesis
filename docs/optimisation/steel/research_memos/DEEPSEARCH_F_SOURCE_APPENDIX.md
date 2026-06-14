# Deepsearch F — Reorganised Source Appendix

**Purpose.** This appendix organises the Deepsearch F sources for the S2 numerical assumption library for the deterministic metallic material-flow LP. The source IDs `F01`–`F20` are kept stable so existing source-card references and parameter-row mappings do not break.

**Use rule.** These sources support an assumption and sensitivity library. They do **not** automatically approve hardcoded model inputs, and public Tata evidence should be used for topology, framing, and validation context rather than as confidential operational truth.

## Critical caveats

- `F15` is still weakly pinned: the title/source is known, but the author and year need verification during the source-card pass.
- `F18`, `F19`, and `F20` are uploaded/repository-only materials. Treat them as modelling/governance precedents, not as public numerical evidence.
- Vendor and technology-provider documents (`F04`–`F07`, `F10`, `F16`) are useful for feasible ranges, operating classes, and sensitivity bounds, but they should not be treated as neutral academic estimates without cross-checking.
- Older downstream/casting sources (`F13`, `F14`) are useful for structural logic and order-of-magnitude reasoning, but should be caveated when used for modern Tata-inspired assumptions.

## Thematic index

| Theme | Source IDs | Main use |
| --- | --- | --- |
| Scope, governance, and modelling precedents | `F20`, `F19`, `F18` | Use these first to keep S2 within its intended thesis/repository role. They are not numerical evidence sources by themselves. |
| Tata IJmuiden route context and public decarbonisation framing | `F01`, `F17` | These sources define the public topology, route framing, and validation context. They should not be treated as confidential Tata operating data. |
| Flexibility, inventory, and buffer guardrails | `F02`, `F03`, `F05`, `F06`, `F14`, `F15` | These sources support the material-flow LP logic: bounded inventories, cyclic or anti-gaming constraints, and feasible decoupling between process stages. |
| Direct reduction, DRI/HBI handling, and DRP technology assumptions | `F04`, `F07`, `F08` | These sources support DRP capacity ranges, DRI/HBI handling classes, metallisation/carbon caveats, and hot/cold DRI decoupling assumptions. |
| BOF/EAF steelmaking process assumptions | `F09`, `F10`, `F11` | These sources support batch-equivalent steelmaking assumptions, tap-to-tap times, heat sizes, hot-metal/scrap shares, and EAF operating bounds. |
| Raw-material coefficients, casting yields, and upstream continuity | `F12`, `F13`, `F16` | These sources support first-pass mass-balance coefficients, casting/yield assumptions, and near-continuous upstream-process treatment. |

## 1. Scope, governance, and modelling precedents

Use these first to keep S2 within its intended thesis/repository role. They are not numerical evidence sources by themselves.

### F20 — *AGENTS.md* / project repository governance file

- **Primary role in S2:** Repository governance and stage discipline
- **Author / institution:** Project repository document
- **Year:** current project file
- **Exact URL / DOI:**
  - Uploaded file only in this chat: `AGENTS.md`
- **Page / table / figure:** Optimisation scope and guardrails
- **Parameter rows / assumptions supported:**
  - `REPO_GOVERNANCE`
  - `STAGE_DISCIPLINE`
  - `DO_NOT_JUMP_TO_FULL_STEEL_MILP`
  - `SCENARIO_PROVENANCE`
  - `NO_HARDCODED_ASSUMPTIONS`

### F19 — Optimising Industrial Participation in the Day-Ahead Electricity Market: A Stochastic Bidding Framework with Risk Management

- **Primary role in S2:** Bidding-method precedent; not an S2 parameter source
- **Author / institution:** Mukunda Badarinath; TU Delft
- **Year:** 2025
- **Exact URL / DOI:**
  - Uploaded file only in this chat: `Master_Thesis_Mukunda_Badarinath.pdf`
- **Page / table / figure:** Summary; Fig. 2.3–2.4; Ch. 5 case-study setup
- **Parameter rows / assumptions supported:**
  - `BIDDING_METHOD_PRECEDENT`
  - `BENCHMARK_LOGIC`
  - `HYDROGEN_VERIFICATION_PRECEDENT`
  - `NOT_S2_PARAMETER_SOURCE`

### F18 — Master Thesis – Modeling the Energy Transition of an Integrated Steel Site: The Case of Tata Steel’s IJmuiden Site

- **Primary role in S2:** Tata-inspired modelling precedent; not approved numerical input
- **Author / institution:** Ioannis Athanasiadis; TU Delft
- **Year:** 2025
- **Exact URL / DOI:**
  - Uploaded file only in this chat: `Master_Thesis_Report_Athanasiadis (1).pdf`
- **Page / table / figure:** Cover/title page; confidentiality statement; methodology/executive summary
- **Parameter rows / assumptions supported:**
  - `MODELLING_STRUCTURE_PRECEDENT`
  - `TATA_INSPIRED_NOT_DIGITAL_TWIN`
  - `REDACTED_VALUES_WARNING`
  - `DO_NOT_USE_AS_APPROVED_NUMERICAL_INPUT`

## 2. Tata IJmuiden route context and public decarbonisation framing

These sources define the public topology, route framing, and validation context. They should not be treated as confidential Tata operating data.

### F01 — Feasibility study on climate-neutral pathways for TSN IJmuiden

- **Primary role in S2:** Public TSN topology and transition anchor
- **Author / institution:** Roland Berger; commissioned by Tata Steel Netherlands & FNV
- **Year:** 2021
- **Exact URL / DOI:**
  - <https://products.tatasteelnederland.com/sites/producttsn/files/TSN%20Climate%20Neutral%20Pathways%20Final%20Report.pdf>
- **Page / table / figure:** p. 1–5; p. 3 production/emissions anchor; p. 5 DRI explanation
- **Parameter rows / assumptions supported:**
  - `TOPOLOGY_TSN_BASELINE_BF_BOF`
  - `TARGET_SITE_ANNUAL_STEEL`
  - `VALIDATION_CO2_ANCHOR`
  - `ROUTE_DRI_TRANSITION`
  - `PUBLIC_TOPOLOGY_ONLY`

### F17 — Technologies to decarbonise the EU steel industry

- **Primary role in S2:** EU steel decarbonisation technology context
- **Author / institution:** Julian Somers; European Commission JRC / Publications Office of the European Union
- **Year:** 2022
- **Exact URL / DOI:**
  - <https://publications.jrc.ec.europa.eu/repository/handle/JRC127468>
  - DOI: <https://doi.org/10.2760/069150>
- **Page / table / figure:** JRC metadata page; report pages to verify in source-card pass
- **Parameter rows / assumptions supported:**
  - `ROUTE_DRP_EAF_CONTEXT`
  - `EU_STEEL_DECARBONISATION_TECH`
  - `HYDROGEN_DRI_CONTEXT`
  - `TECHNOLOGY_SCREENING_CONTEXT`

## 3. Flexibility, inventory, and buffer guardrails

These sources support the material-flow LP logic: bounded inventories, cyclic or anti-gaming constraints, and feasible decoupling between process stages.

### F02 — Flexibility options in a decarbonising iron and steel industry

- **Primary role in S2:** Inventory/flexibility modelling logic
- **Author / institution:** Annika Boldrini, Derck Koolen, Wina Crijns-Graus, Ernst Worrell, Machteld van den Broek
- **Year:** 2024
- **Exact URL / DOI:**
  - <https://doi.org/10.1016/j.rser.2023.113988>
- **Page / table / figure:** Eq. 6–7 storage balance/cyclic logic; tables/sections on flexible steel options
- **Parameter rows / assumptions supported:**
  - `INV_CYCLIC_TERMINAL`
  - `INV_INITIAL_FINAL_EQUAL`
  - `ANTI_FAKE_FLEXIBILITY`
  - `BUFFER_BOUNDED_STORE`
  - `DRP_EAF_FLEXIBILITY`
  - `AVAILABLE_HOURS_OR_CAPACITY_FACTOR`

### F03 — Best Available Techniques (BAT) Reference Document for Iron and Steel Production

- **Primary role in S2:** Hot-metal buffer and BF–BOF coupling evidence
- **Author / institution:** Rainer Remus, Miguel A. Aguado-Monsonet, Serge Roudier, Luis Delgado Sancho; European Commission JRC / EIPPCB
- **Year:** 2013
- **Exact URL / DOI:**
  - <https://publications.jrc.ec.europa.eu/repository/bitstream/JRC69967/lfna25521enn.pdf>
  - DOI: <https://doi.org/10.2791/97469>
- **Page / table / figure:** Section 7.1.1; p. 381–382 hot-metal ladles/mixers
- **Parameter rows / assumptions supported:**
  - `BUF_HOT_METAL_CAPACITY`
  - `HOT_METAL_MIXER_RANGE`
  - `HOT_METAL_BUFFER_FEASIBILITY_ONLY`
  - `BF_TO_BOF_COUPLING`

### F05 — Direct From Midrex, 3rd Quarter 2022: Getting the Most from Direct Reduced Iron — Operational Results of MIDREX® Hot Transport–Hot Charging

- **Primary role in S2:** HDRI/EAF decoupling and hot-charging context
- **Author / institution:** Brian Voelker and Sean Boyle; Midrex Technologies
- **Year:** 2022
- **Exact URL / DOI:**
  - <https://www.midrex.com/wp-content/uploads/Midrex-DFM-3rdQtr2022-Final-1.pdf>
- **Page / table / figure:** p. 4 Table I–II; p. 6–8 HTV/feed-bin discussion
- **Parameter rows / assumptions supported:**
  - `BUF_HDRI_SURGE`
  - `BUF_DRI_EAF_DECOUPLING`
  - `EAF_TAP_TO_TAP`
  - `HDRI_THERMAL_CAVEAT`
  - `EAF_PRODUCTIVITY_HDRI`

### F06 — Hot Transport Vessel (HTV) System: Hot Transport Vessel for Hot Charging DRI

- **Primary role in S2:** HTV/HBI storage class and DRI sensitivity evidence
- **Author / institution:** Midrex Technologies
- **Year:** 2014 / undated brochure
- **Exact URL / DOI:**
  - <https://www.midrex.com/wp-content/uploads/Hot_Transport_-_HTV.pdf>
- **Page / table / figure:** p. 1 HTV size and thermal value; p. 2 HBI storage
- **Parameter rows / assumptions supported:**
  - `BUF_HTV_CAPACITY`
  - `HDRI_SHORT_TRANSFER`
  - `HBI_STORAGE_CLASS`
  - `THERMAL_LOSS_REHEAT_PROXY`
  - `BUF_DRI_SENSITIVITY`

### F14 — The Hot Strip Mill Production Scheduling Problem in the Steel Industry: A Heuristic Approach Using Tabu Search

- **Primary role in S2:** Downstream hot-strip/slab scheduling context
- **Author / institution:** Leovigildo Lopez-Garcia; University of Toronto
- **Year:** 1997
- **Exact URL / DOI:**
  - <https://www.collectionscanada.gc.ca/obj/s4/f2/dsk2/ftp02/NQ35442.pdf>
- **Page / table / figure:** p. 17–26; reheating-furnace sections
- **Parameter rows / assumptions supported:**
  - `HSM_DOWNSTREAM_SINK`
  - `SLAB_WIP_THERMAL_CLASS`
  - `REHEAT_TIME_PROXY`
  - `HOT_WARM_COLD_SLAB_CAVEAT`
  - `HSM_SCHEDULING_CONTEXT`

### F15 — Improving the operations of a Slab Yard through the implementation of best practices

- **Primary role in S2:** Slab-yard order-of-magnitude sensitivity source
- **Author / institution:** University of Pretoria repository; author/year to verify in source-card pass
- **Year:** not pinned
- **Exact URL / DOI:**
  - <https://repository.up.ac.za/server/api/core/bitstreams/8240a454-8f3c-4704-972b-c5201497e0ec/content>
- **Page / table / figure:** p. 5–6 inventory figures; p. 31 safety stock; p. 37 schedule-based inventory
- **Parameter rows / assumptions supported:**
  - `BUF_SLAB_YARD_ORDER_OF_MAGNITUDE`
  - `SLAB_YARD_DAYS_SCALE_SENSITIVITY`
  - `WIP_BUFFER_WEAK_TRANSFER`
  - `DO_NOT_USE_AS_TATA_TRUTH`

## 4. Direct reduction, DRI/HBI handling, and DRP technology assumptions

These sources support DRP capacity ranges, DRI/HBI handling classes, metallisation/carbon caveats, and hot/cold DRI decoupling assumptions.

### F04 — The MIDREX® Process

- **Primary role in S2:** MIDREX DRP operating range and continuity evidence
- **Author / institution:** Midrex Technologies, Inc.
- **Year:** 2018
- **Exact URL / DOI:**
  - <https://www.midrex.com/wp-content/uploads/MIdrex_Process_Brochure_4-12-18.pdf>
- **Page / table / figure:** p. 3 module sizing; p. 5 operating hours; p. 6 minimum operation
- **Parameter rows / assumptions supported:**
  - `PROC_DRP_CAPACITY_RANGE`
  - `PROC_DRP_CONTINUITY_CLASS`
  - `PROC_DRP_MIN_LOAD`
  - `SCALE_DRP_AVAILABLE_HOURS`
  - `DRP_NOT_BATCH`

### F07 — ENERGIRON: DRI Technology by Tenova and Danieli

- **Primary role in S2:** ENERGIRON DRP/DRI technical range and vendor sensitivity
- **Author / institution:** Tenova / Danieli
- **Year:** undated / 2026 URL path
- **Exact URL / DOI:**
  - <https://tenova.com/sites/default/files/files/solutions/2026/ENERGIRON_Brochure_ENG.pdf>
- **Page / table / figure:** p. 4–5 DRI/HBI handling; p. 7 capacity and ore-to-DRI numbers
- **Parameter rows / assumptions supported:**
  - `PROC_DRP_CAPACITY_RANGE`
  - `COEFF_ORE_TO_DRI`
  - `DRI_METALLIZATION`
  - `DRI_CARBON`
  - `CDRI_HBI_HANDLING_CLASS`
  - `DRP_VENDOR_SENSITIVITY`

### F08 — Reoxidation Behavior of the Direct Reduced Iron and Hot Briquetted Iron during Handling and Their Integration into Electric Arc Furnace Steelmaking: A Review

- **Primary role in S2:** DRI/HBI handling, reoxidation, and EAF integration review
- **Author / institution:** Lina Kieush, Stefanie Lesiak, Johannes Rieger, Melanie Leitner, Lukas Schmidt, Omid Daghagheleh
- **Year:** 2024
- **Exact URL / DOI:**
  - <https://www.k1-met.com/fileadmin/user_upload/Publications/Journal_articles_open_access/Kieush__L.__Lesiak__S.__Rieger__J.__Leitner__M.__Schmidt__L.__Daghagheleh__O._metals-14-00873-v2.pdf>
  - DOI: <https://doi.org/10.3390/met14080873>
- **Page / table / figure:** Table 6; Fig. 9
- **Parameter rows / assumptions supported:**
  - `PROC_EAF_BATCH_EQUIVALENT`
  - `EAF_TAP_TO_TAP_RANGE`
  - `COEFF_EAF_YIELD_SCRAP`
  - `COEFF_EAF_YIELD_DRI`
  - `DRI_HBI_REOXIDATION_CAVEAT`

## 5. BOF/EAF steelmaking process assumptions

These sources support batch-equivalent steelmaking assumptions, tap-to-tap times, heat sizes, hot-metal/scrap shares, and EAF operating bounds.

### F09 — 70 Years of LD-Steelmaking—Quo Vadis?

- **Primary role in S2:** BOF process, hot-metal share, scrap share, and heat-time evidence
- **Author / institution:** Jürgen Cappel, Frank Ahrenhold, Martin W. Egger, Herbert Hiebler, Johannes Schenk
- **Year:** 2022
- **Exact URL / DOI:**
  - <https://www.k1-met.com/fileadmin/user_upload/Publications/Journal_articles_open_access/Cappel__Schenk_et_al._Metals__2022_.pdf>
  - DOI: <https://doi.org/10.3390/met12060912>
- **Page / table / figure:** p. 6–7 hot-metal ratio; Fig. 7; p. 12 heat times; p. 15 slag
- **Parameter rows / assumptions supported:**
  - `PROC_BOF_BATCH_EQUIVALENT`
  - `BOF_HOT_METAL_SHARE`
  - `BOF_SCRAP_SHARE`
  - `BOF_HEAT_DURATION`
  - `COEFF_BOF_SLAG_PROXY`

### F10 — Modeling of Electric Arc Furnaces (EAF) with electromagnetic stirring

- **Primary role in S2:** Modern EAF tap-to-tap vendor/technical context
- **Author / institution:** Ola Widlund, Ulf Sand, Olof Hjortstam, Xiaojing Zhang; ABB AB Corporate Research / ABB Metallurgy
- **Year:** undated technical paper
- **Exact URL / DOI:**
  - <https://library.e.abb.com/public/c6577f6a9f91b38485257961006aa934/Modeling%20of%20Electric%20Arc.pdf>
- **Page / table / figure:** p. 1 modern EAF tap-to-tap statement
- **Parameter rows / assumptions supported:**
  - `EAF_FAST_TAP_TO_TAP_BOUND`
  - `PROC_EAF_BATCH_EQUIVALENT`
  - `EAF_VENDOR_CONTEXT_ONLY`

### F11 — Electric Arc Furnace Process Modelling and Simulation

- **Primary role in S2:** EAF heat size, tap weight, hot heel, and batch duration
- **Author / institution:** Hermann Völkl; TU Wien
- **Year:** 2023
- **Exact URL / DOI:**
  - <https://repositum.tuwien.at/bitstream/20.500.12708/158341/1/Voelkl%20Hermann%20-%202023%20-%20Electric%20Arc%20Furnace%20Process%20Modelling%20and%20Simulation.pdf>
- **Page / table / figure:** p. 74 Table 24
- **Parameter rows / assumptions supported:**
  - `EAF_HEAT_SIZE`
  - `EAF_TAP_WEIGHT`
  - `EAF_HOT_HEEL`
  - `EAF_BATCH_DURATION`
  - `EAF_HOURLY_EQUIVALENT_THROUGHPUT`

## 6. Raw-material coefficients, casting yields, and upstream continuity

These sources support first-pass mass-balance coefficients, casting/yield assumptions, and near-continuous upstream-process treatment.

### F12 — Steel and raw materials: Fact sheet

- **Primary role in S2:** BF–BOF raw-material coefficient context
- **Author / institution:** World Steel Association
- **Year:** 2023
- **Exact URL / DOI:**
  - <https://worldsteel.org/wp-content/uploads/Fact-sheet-raw-materials-2023-1.pdf>
- **Page / table / figure:** p. 1 BF–BOF raw-material coefficients; p. 2 scrap discussion
- **Parameter rows / assumptions supported:**
  - `COEFF_BF_BOF_IRON_ORE`
  - `COEFF_BF_BOF_COAL`
  - `COEFF_BF_BOF_LIMESTONE`
  - `COEFF_BOF_RECYCLED_STEEL`
  - `RAW_MATERIAL_EXTERNAL_SUPPLY`

### F13 — Recent Trends and Future Prospects of Continuous Casting Technology

- **Primary role in S2:** Casting yield and continuous-casting sequence context
- **Author / institution:** Hirohiko Okumura; Nippon Steel Technical Report No. 61
- **Year:** 1994
- **Exact URL / DOI:**
  - <https://www.nipponsteel.com/en/tech/report/nsc/pdf/6102.pdf>
- **Page / table / figure:** Table 1 around p. 2
- **Parameter rows / assumptions supported:**
  - `COEFF_CASTING_YIELD`
  - `PROC_CASTING_CONTINUOUS_SEQUENCE`
  - `CASTING_TO_SLAB_YIELD`
  - `CASTING_OLD_TECH_REFERENCE_SENSITIVITY`

### F16 — Operation of Cutting-Edge Coke Oven Having all of Durability, Safety and Efficiency

- **Primary role in S2:** Coke-oven continuity and capacity example
- **Author / institution:** Paul Wurth IHI Co., Ltd. / IHI technical information
- **Year:** 2017
- **Exact URL / DOI:**
  - <https://www.ihi.co.jp/en/technology/techinfo/contents_no/__icsFiles/afieldfile/2023/06/17/e8259f5361c09473fa1f08cd63e362ca.pdf>
- **Page / table / figure:** p. 1–2 coke-oven capacities and continuity wording
- **Parameter rows / assumptions supported:**
  - `PROC_COKE_OVEN_CONTINUITY`
  - `COKE_OVEN_CAPACITY_EXAMPLE`
  - `COKE_NEAR_MUST_RUN`
  - `COKE_BUFFER_WEAK_EVIDENCE`

## Parameter-row coverage cross-reference

This index is source-to-parameter rather than parameter-to-source. It is meant to help the source-card pass check whether every S2 row has explicit evidence support before being promoted to a model input.

| Source ID | Primary role | Supported parameter rows / assumptions |
| --- | --- | --- |
| `F20` | Repository governance and stage discipline | `REPO_GOVERNANCE`, `STAGE_DISCIPLINE`, `DO_NOT_JUMP_TO_FULL_STEEL_MILP`, `SCENARIO_PROVENANCE`, `NO_HARDCODED_ASSUMPTIONS` |
| `F19` | Bidding-method precedent; not an S2 parameter source | `BIDDING_METHOD_PRECEDENT`, `BENCHMARK_LOGIC`, `HYDROGEN_VERIFICATION_PRECEDENT`, `NOT_S2_PARAMETER_SOURCE` |
| `F18` | Tata-inspired modelling precedent; not approved numerical input | `MODELLING_STRUCTURE_PRECEDENT`, `TATA_INSPIRED_NOT_DIGITAL_TWIN`, `REDACTED_VALUES_WARNING`, `DO_NOT_USE_AS_APPROVED_NUMERICAL_INPUT` |
| `F01` | Public TSN topology and transition anchor | `TOPOLOGY_TSN_BASELINE_BF_BOF`, `TARGET_SITE_ANNUAL_STEEL`, `VALIDATION_CO2_ANCHOR`, `ROUTE_DRI_TRANSITION`, `PUBLIC_TOPOLOGY_ONLY` |
| `F17` | EU steel decarbonisation technology context | `ROUTE_DRP_EAF_CONTEXT`, `EU_STEEL_DECARBONISATION_TECH`, `HYDROGEN_DRI_CONTEXT`, `TECHNOLOGY_SCREENING_CONTEXT` |
| `F02` | Inventory/flexibility modelling logic | `INV_CYCLIC_TERMINAL`, `INV_INITIAL_FINAL_EQUAL`, `ANTI_FAKE_FLEXIBILITY`, `BUFFER_BOUNDED_STORE`, `DRP_EAF_FLEXIBILITY`, `AVAILABLE_HOURS_OR_CAPACITY_FACTOR` |
| `F03` | Hot-metal buffer and BF–BOF coupling evidence | `BUF_HOT_METAL_CAPACITY`, `HOT_METAL_MIXER_RANGE`, `HOT_METAL_BUFFER_FEASIBILITY_ONLY`, `BF_TO_BOF_COUPLING` |
| `F05` | HDRI/EAF decoupling and hot-charging context | `BUF_HDRI_SURGE`, `BUF_DRI_EAF_DECOUPLING`, `EAF_TAP_TO_TAP`, `HDRI_THERMAL_CAVEAT`, `EAF_PRODUCTIVITY_HDRI` |
| `F06` | HTV/HBI storage class and DRI sensitivity evidence | `BUF_HTV_CAPACITY`, `HDRI_SHORT_TRANSFER`, `HBI_STORAGE_CLASS`, `THERMAL_LOSS_REHEAT_PROXY`, `BUF_DRI_SENSITIVITY` |
| `F14` | Downstream hot-strip/slab scheduling context | `HSM_DOWNSTREAM_SINK`, `SLAB_WIP_THERMAL_CLASS`, `REHEAT_TIME_PROXY`, `HOT_WARM_COLD_SLAB_CAVEAT`, `HSM_SCHEDULING_CONTEXT` |
| `F15` | Slab-yard order-of-magnitude sensitivity source | `BUF_SLAB_YARD_ORDER_OF_MAGNITUDE`, `SLAB_YARD_DAYS_SCALE_SENSITIVITY`, `WIP_BUFFER_WEAK_TRANSFER`, `DO_NOT_USE_AS_TATA_TRUTH` |
| `F04` | MIDREX DRP operating range and continuity evidence | `PROC_DRP_CAPACITY_RANGE`, `PROC_DRP_CONTINUITY_CLASS`, `PROC_DRP_MIN_LOAD`, `SCALE_DRP_AVAILABLE_HOURS`, `DRP_NOT_BATCH` |
| `F07` | ENERGIRON DRP/DRI technical range and vendor sensitivity | `PROC_DRP_CAPACITY_RANGE`, `COEFF_ORE_TO_DRI`, `DRI_METALLIZATION`, `DRI_CARBON`, `CDRI_HBI_HANDLING_CLASS`, `DRP_VENDOR_SENSITIVITY` |
| `F08` | DRI/HBI handling, reoxidation, and EAF integration review | `PROC_EAF_BATCH_EQUIVALENT`, `EAF_TAP_TO_TAP_RANGE`, `COEFF_EAF_YIELD_SCRAP`, `COEFF_EAF_YIELD_DRI`, `DRI_HBI_REOXIDATION_CAVEAT` |
| `F09` | BOF process, hot-metal share, scrap share, and heat-time evidence | `PROC_BOF_BATCH_EQUIVALENT`, `BOF_HOT_METAL_SHARE`, `BOF_SCRAP_SHARE`, `BOF_HEAT_DURATION`, `COEFF_BOF_SLAG_PROXY` |
| `F10` | Modern EAF tap-to-tap vendor/technical context | `EAF_FAST_TAP_TO_TAP_BOUND`, `PROC_EAF_BATCH_EQUIVALENT`, `EAF_VENDOR_CONTEXT_ONLY` |
| `F11` | EAF heat size, tap weight, hot heel, and batch duration | `EAF_HEAT_SIZE`, `EAF_TAP_WEIGHT`, `EAF_HOT_HEEL`, `EAF_BATCH_DURATION`, `EAF_HOURLY_EQUIVALENT_THROUGHPUT` |
| `F12` | BF–BOF raw-material coefficient context | `COEFF_BF_BOF_IRON_ORE`, `COEFF_BF_BOF_COAL`, `COEFF_BF_BOF_LIMESTONE`, `COEFF_BOF_RECYCLED_STEEL`, `RAW_MATERIAL_EXTERNAL_SUPPLY` |
| `F13` | Casting yield and continuous-casting sequence context | `COEFF_CASTING_YIELD`, `PROC_CASTING_CONTINUOUS_SEQUENCE`, `CASTING_TO_SLAB_YIELD`, `CASTING_OLD_TECH_REFERENCE_SENSITIVITY` |
| `F16` | Coke-oven continuity and capacity example | `PROC_COKE_OVEN_CONTINUITY`, `COKE_OVEN_CAPACITY_EXAMPLE`, `COKE_NEAR_MUST_RUN`, `COKE_BUFFER_WEAK_EVIDENCE` |
