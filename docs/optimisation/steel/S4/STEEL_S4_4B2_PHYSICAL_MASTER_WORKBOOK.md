# Steel S4.4b2 Physical Master Workbook

## Goal

S4.4b2 creates a canonical physical-model authoring workbook for:

- `C0_current_BF_BOF_reference`
- `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`

The workbook uses a PyPSA-inspired ontology: Buses, Links, Stores, Loads, and Generators. It remains solver-independent and does not migrate the existing S4.4b inputs into S4.4c.

This workbook is the canonical physical authoring surface, not the executable model input surface. Executable use requires human review and explicit migration into the S4.4 development input tables.

## Files

- Workbook: `data/03_Optimisation/inputs/assets/steel/S4/s4_4b2_physical_master_workbook/steel_c0_c1_physical_model_master.xlsx`
- Compiled review CSVs: `data/03_Optimisation/inputs/assets/steel/S4/s4_4b2_physical_master_workbook/compiled_review/`
- Builder/validator/compiler: `scripts/Data/04_Steel_Test_Case/steel/s4_4b2_physical_master_workbook.py`
- Runner: `scripts/Data/04_Steel_Test_Case/run_s4_4b2_physical_master_workbook.py`
- Tests: `scripts/Data/04_Steel_Test_Case/tests/test_s4_4b2_physical_master_workbook.py`

## Source Hierarchy

The workbook follows the frozen repository hierarchy:

1. Formal public Tata/MER/eMJV-style sources and registered source cards for Tata-specific public topology and numeric evidence.
2. Athanasiadis as public-thesis modelling-architecture precedent for the process, WAG, steam, source, and Store network.
3. Badarinath as secondary precedent for electrical abstraction, DRI buffer decoupling, rolling-horizon inventory policy, and EAF semi-continuous formulation.
4. Repository freezes and policy documents for selected boundary and governance decisions.
5. Deepsearch memos as discovery and candidate-evidence context only.

The raw Athanasiadis and Badarinath PDFs are archived under `data/03_Optimisation/inputs/assets/steel/source_evidence/`, but the source-card register, candidate-evidence register, assumption register, and workbook evidence links remain the authoritative working evidence layer. Direct PDF inspection is allowed only for targeted provenance repair, locator verification, or conflict checks. Any such inspection must produce patch proposals for source cards, candidate evidence, assumptions, or workbook evidence links; it must not create executable inputs directly.

Source-to-input workflow:

1. Source -> source card.
2. Value or range -> candidate evidence register.
3. Modelling interpretation -> assumption register.
4. Physical structure -> workbook.
5. Machine-readable review -> compiled review CSVs.
6. Executable use -> reviewed migration into development input tables.
7. Thesis use -> later approval gate.

## Scope

Included:

- material, utility, energy, WAG, product, and emissions carriers;
- C0 and C1 asset activation as a shared ontology with C1 as a change set over C0;
- separate BFG, COG, and BOFG carriers and buses;
- WAG mixing-controller rows and sink eligibility;
- steam, oxygen, WAG holders, DRI, hot metal, slab/WIP, product target, and CO2 accumulator classifications;
- validation anchors as non-executable rows;
- conflicts and gaps, including the KGF1/KGF2 closure conflict.

Current topology decisions:

- `C0` is the current BF-BOF reference.
- `C1` is the Phase 1 hybrid BF-BOF plus NG-DRP plus EAF configuration.
- `C1` is a change set over `C0`.
- `C1` first closures: BF7 inactive and KGF2 / Coking Plant 2 inactive.
- `C1` retained assets: BF6 and KGF1 / Coking Plant 1.

Ontology principles:

- buses carry physical carriers or accounting nodes;
- links transform or move material, utility, energy, WAG, product, or emissions carriers;
- stores are physical buffers only when capacity and terminal policy can be defined before executable use;
- loads and generators represent exogenous withdrawals or supplies;
- link ports define multi-input and multi-output process structure;
- validation anchors are non-executable checks;
- accounting accumulators are not physical flexibility assets.

WAG and buffer principles:

- BFG, COG, and BOFG remain separate carriers;
- WAG aggregate exists only after explicit mixing;
- direct WAG market valuation is not allowed;
- steam defaults to a bus, not a store, unless evidence supports storage;
- material stores need finite capacity and terminal policy before executable use;
- hot/cold slab states remain part of the physical design direction.

Excluded:

- objective terms, prices, tariffs, revenues, DA dispatch, bidding, stochasticity, CVaR, quarter-hour logic, D+4, mFRR, and oracle/perfect foresight;
- migration of S4.4c modelbuilder inputs;
- full Tata digital-twin claims.

## Stage Gate

Expected S4.4b2 decision:

`ready_for_human_physical_model_review`

This must not be interpreted as:

- `ready_for_unified_model_execution`
- thesis usable
- Tata validated

Human review is required before any workbook-derived migration into executable model inputs.

`S4.4c` may solve only rows that exist in executable development inputs. Workbook-only rows, compiled-review-only rows, and review-only candidate values must not be used as dispatch inputs or thesis evidence.
