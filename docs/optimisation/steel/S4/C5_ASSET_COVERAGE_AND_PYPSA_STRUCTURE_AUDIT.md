# S4.4c/C5 Asset Coverage and PyPSA Structure Audit

## Purpose and scope

This audit records the current coverage of the public Tata Steel IJmuiden-inspired S4.4c/C5 plant-by-plant physical/accounting model. It is an audit-only artifact: no plant physics, coefficients, baselines, optimisation objective, market logic, or source-card values are changed here.

The model remains development-only. It is not a confidential Tata digital twin and it is not thesis-approved. Public MER/source-card anchors, Athanasiadis-style process-network structure, and Badarinath-style steel flexibility framing are used as modelling context, not as exact Tata truth.

## Current C5 implementation summary

The latest accepted sequence through `C5n_b` is a deterministic plant-ledger and report stack. It is PyPSA-inspired, but the current C5 artifacts are mostly sequential physical/accounting layers and compact healthchecks rather than one fully solved PyPSA network.

Implemented or active development layers include:

- KGF/coking plants: coke output, dry coal input, electricity, steam proxy, COG generation, KGF COG underfiring, net COG surplus, and KGF CO2 diagnostic.
- BF and BF hot stove: hot metal driver, coke/PCI/oxygen/electricity/steam demand, gross BFG generation, hot-stove gas use, net BFG to WAG, and BF aggregate CO2 diagnostic.
- BOF/OSF: BOF liquid steel, hot metal and scrap inputs, oxygen demand, electricity, BOFG generation, and BOF direct CO2 diagnostic.
- C5k production policy: 6.75 Mt/y active target, C1 BOF/EAF route split, and no-buffer BF hot-metal normalisation.
- HSM/WBW: downstream HSM/WBW routing, slab buffer diagnostics, C5l_d base hot-charge cap at 0.50, charge-specific reheat, rolling electricity, and HSM WAG controller.
- Sinter: per-timestep BF-hot-metal-coupled sinter output, iron ore input, electricity, COG/NG gas heat, steam proxy demand, aggregate CO2, and no useful WAG production.
- Coke reconciliation: repaired BF coke-demand driver and bounded reconciliation sensitivity reporting, without external coke as accepted baseline.
- PEFA/Pelletizing: production-coupled fired-pellet output, iron ore input, electricity, BOFG/COG/NG gas heat eligibility, solid fuel diagnostic, aggregate CO2, waste-gas reporting only, no BFG use, and no useful WAG generation.
- Pellet burden and bulk solids: single fired-pellets proxy, imported pellet supply, BF/DRP pellet demand diagnostics, and practically non-binding coke/sinter/pellet storage policy with no-free-material safeguards.
- Compact healthcheck and plant ledger: current C5 process electricity scope, WAG carrier ledgers, steam proxy status, CO2 guard status, anchor gaps, and red flags.

Important non-coverage:

- C1 DRP and EAF are not yet full physical process layers in the C5 baseline. C5n_b uses DRP-related pellet demand context, but the NG-DRP, DRI buffer, and EAF material/energy/CO2 process chain is not implemented as an active plant route.
- DSP exists as downstream routing/accounting context, not as a full process plant.
- Oxygen demand is reported, but there is no Linde/ASU/oxygen plant or oxygen buffer layer.
- WAG boilers, Vattenfall/IJ01/VN25, flaring, and residual interface rows preserve balances, but they are not yet physical generator/boiler/economic plant implementations.
- Current process electricity totals are explicitly current-C5-scope process totals, not full-site electricity demand or import/export cost.

## PyPSA-inspired structure

### Buses and carriers

The current C5 stack uses named flows and ledgers analogous to PyPSA buses and carriers:

- Material carriers: liquid steel, hot metal, slab, HRC/WBW/DSP final-product proxy, coke, sinter, fired pellets, iron ore, scrap, DRI context, imported pellets, imported cold slab.
- Energy carriers: electricity, process heat, NG, BFG, COG, BOFG, and separate WAG residuals.
- Utility carriers: steam proxy demand, oxygen demand, and solid fuel diagnostic drivers.
- Accounting carriers: aggregate diagnostic CO2, direct CO2 diagnostics, waste gas reporting, validation anchors, inventory drift, and red flags.

BFG, COG, and BOFG remain separate carriers. Mixed or aggregate WAG is not a direct market commodity in the accepted C5 layers.

### Links and process units

Plant layers are represented as production-coupled links or accounting links. Examples:

- KGF/coking: dry coal to coke plus COG generation and underfiring self-use.
- BF: coke/PCI/oxygen/electricity/steam to hot metal plus BFG and aggregate CO2 diagnostic.
- BF hot stove: eligible gases to BF heating demand.
- BOF/OSF: hot metal and scrap to BOF liquid steel plus BOFG and CO2 diagnostic.
- HSM: slab to HRC/WBW with rolling electricity and reheat heat demand.
- Sinter: BF-hot-metal-coupled sinter production from iron ore plus electricity, COG/NG heat, steam proxy, and CO2.
- PEFA: fired-pellet production with electricity, BOFG/COG/NG heat eligibility, solid fuel, aggregate CO2, and waste gas reporting only.

The current stack generally implements these links through executable development input rows and report builders rather than a unified PyPSA component table.

### Stores and buffers

Current physical/accounting store behavior includes:

- HSM slab age-bucket buffer and terminal inventory diagnostics.
- Coke, sinter, and fired-pellet bulk-solid storage policy set to practically non-binding capacity with inventory drift diagnostics.
- Pellet inventory balance diagnostics with no hidden free supply.

Missing or deferred stores include DRI buffer, oxygen buffer, WAG holders, detailed stockyard/blending stores, and full steam network storage.

### Loads

Implemented loads include process electricity for KGF, BF, BOF, HSM rolling, Sinter, and PEFA; HSM reheat; Sinter gas heat; PEFA gas heat; BF hot-stove heat; oxygen demand accounting; steam proxy demand where governed; and NG backup where allowed.

Residual site electricity and residual NG loads are not yet implemented as governed boundary loads.

### Generators and interfaces

The C5 WAG ledger contains residual/interface rows for boilers, Vattenfall/IJ01/VN25-style interfaces, and flaring. These preserve carrier balances and make residual WAG visible, but they are not yet full generator, boiler, steam, electricity-export, or economic dispatch models.

There is no full-site electricity import/export convention, no onsite generation accounting sufficient for DA economics, and no WAG export revenue.

### Link-port and multi-input/output pattern

C5 multi-input/output behavior is handled by explicit carrier ledgers and eligibility constraints:

- KGF gross COG minus underfiring self-use becomes net COG.
- BF gross BFG minus hot-stove demand becomes net BFG.
- BOFG enters the WAG ledger from BOF generation.
- HSM may use BFG, COG, BOFG, or NG for reheat.
- Sinter may use COG or NG only.
- PEFA may use BOFG/NG in Malerij and COG/NG in Branderij; BFG is blocked.
- PEFA waste gas is reporting/emissions only and cannot enter useful WAG balances.

### Ledgers and healthchecks

The compact C5 healthchecks are the current governing visibility layer. They report plant coverage, current-C5 process electricity, WAG carrier balance, steam proxy status, CO2 double-count guards, storage binding flags, anchor gaps, and red flags. These are critical because several assets are implemented as accounting layers before they become full optimisation components.

## Plant-by-plant coverage

The CSV matrix at `data/03_Optimisation/inputs/assets/steel/S4/c5_asset_coverage_audit/c5_asset_coverage_matrix.csv` is the detailed plant-by-plant classification. The high-level picture is:

- Implemented physical/accounting development layers: KGF, BF, BF hot stove, BOF/OSF, HSM/WBW, Sinter, PEFA, pellet burden balance, and bulk-solid storage diagnostics.
- Partial layers: WAG network, downstream DSP/final-product accounting, C1 EAF route, C1 DRP route context, boilers, Vattenfall/generator interface, steam, oxygen, consolidated CO2, and full-site electricity boundary.
- Missing or blocked route-critical layers: C1 NG-DRP, DRI buffer, C1 EAF process physics, DSP process physics, Linde/ASU oxygen plant, and oxygen buffers.

## Missing and partial coverage versus Athanasiadis, Badarinath, and MER context

MER/source-card topology supports the current presence of KGF, PEFA, Sinter, BF, BOF/OSF, HSM/WBW/DSP routing, WAG carriers, oxygen demand, steam, and utility interfaces. Badarinath adds the Phase 1 C1 electrification context: NG-DRP, DRI buffer, EAF, and decoupled operational flexibility. Athanasiadis provides the PyPSA-style buses, links, stores, loads, generators, WAG, steam, and electricity-network precedent.

The largest current mismatch is that C1 is still not a full electrified production route in C5. C5k carries the C1 route split and C5n_b carries pellet-demand context, but C1 DRP, DRI buffer, and EAF have not yet been implemented as active process layers. This is the main blocker before deterministic DA/economic interpretation of C1.

## Blockers before deterministic DA/economics

High-priority blockers:

- C1 DRP/EAF/DRI buffer: without this, C1 electrified route electricity, NG, oxygen, CO2, flexibility, and DRI-buffer decoupling are not represented.
- DSP/downstream process layer: without this, HSM/DSP routing is not enough for downstream electricity/energy/product accounting.
- Linde/ASU/oxygen interface: BOF and future EAF/DRP oxygen demands are currently demand-side accounting only.
- Steam/boiler utility closure: Sinter, KGF, BF, and future utilities need a visible steam supply model or explicit proxy boundary.
- Electricity boundary and generator/interface layer: current process electricity is not full-site electricity, and Vattenfall/IJ01/VN25 rows are not generator economics.

Medium-priority blockers:

- WAG holders and mixed-gas control: current WAG ledgers balance carriers, but storage/holder dynamics and mixed-gas constraints remain deferred.
- Residual electricity and NG loads: these must be explicit boundary loads if used, not calibration slack.
- Consolidated CO2: current diagnostic CO2 is useful for healthchecks but not ETS, not full site, and not thesis-approved.
- Stockyards and raw-material blending: PEFA/Sinter/pellet accounting exists, but stockyard quality and blending remain absent.

## Recommended next stages

The detailed stage table is stored at `data/03_Optimisation/inputs/assets/steel/S4/c5_asset_coverage_audit/c5_recommended_next_stages.csv`.

Recommended order:

1. Add a minimal C1 NG-DRP physical layer.
2. Add EAF process physics and DRI buffer accounting.
3. Harden DSP/casting/downstream accounting.
4. Add Linde/ASU oxygen interface and oxygen buffers.
5. Add steam boilers and steam utility closure.
6. Add electricity interface, residual loads, and generator accounting.

This order prioritises C1 route meaning before utility/economic completeness. Boilers, Vattenfall, and residual electricity are important, but their interpretation depends on the core production route being physically visible first.

## Red flags if implementation continues without closing gaps

- C1 DRP/EAF absent: C1 DA or economics results would not represent the main electrified route.
- DRI buffer absent: Badarinath-style decoupling and flexibility claims are not supported.
- DSP absent: HSM/DSP split can be reported, but downstream product energy claims remain incomplete.
- Linde/ASU absent: oxygen demand exists without supply-side accounting.
- Boilers/steam absent: WAG-to-steam and steam-demand closure cannot be claimed.
- Generator/interface layer absent: Vattenfall/IJ01/VN25 and full-site electricity import/export claims remain blocked.
- Residual loads absent: current-C5 process electricity must not be labelled full-site electricity.
- CO2 remains diagnostic: do not use it for ETS objective steering or full-site emissions claims.

## No-behaviour-change confirmation

This audit only creates documentation and compact CSV artifacts. It does not alter executable development inputs, model code, coefficients, C5 baselines, runners, or generated stage reports.
