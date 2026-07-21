# HSM / WBW Parameters Source Card

Status: candidate source-card memo, development-only.

Thesis usability: false.

This memo records a compact public/generic Hot Strip Mill / Warmbandwalserij
parameter set for development diagnostics in
`S4.4c5l_HSM_WBW_minimal_integration`. It is not an approved executable thesis
input table, not exact Tata truth, and not a calibration target. Values may be
migrated only into labelled development input rows with explicit governance
metadata, review caveats, and sensitivity requirements.

## Process Scope

The first HSM/WBW layer is represented as downstream physical/accounting
diagnostics:

```text
slab input
  -> HSM/WBW
  -> hot rolled coil / gewalste rollen output
  + reheating fuel demand
  + rolling electricity demand
  + material loss/internal scrap diagnostic
```

HSM/WBW is a WAG/NG-consuming downstream process sink in this stage. It is not a
WAG producer, not a product-revenue asset, and not a market-dispatch component.

## Core Candidate Coefficients

| Parameter | Value | Range | Unit | Status |
|---|---:|---:|---|---|
| `HSM_OUTPUT_BASIS` | `t_hot_rolled_coil` | n/a | basis | candidate/development |
| `HSM_SLAB_INPUT_T_PER_T_HRC` | 1.10 | 1.07-1.15 | t slab / t HRC | retired broad development proxy; historical sensitivity only |
| `HSM_SLAB_INPUT_T_PER_T_HRC_GATE2_CENTRAL` | 1.06 | 1.01-1.073 | t slab / t HRC | governed Gate-2 development central; source-boundary reconciled |
| `HSM_REHEAT_ENERGY_GJ_PER_T_HRC` | 1.35 | 1.2-1.5 | GJ / t HRC | candidate/development |
| `HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC` | 0.070 | 0.028-0.111 | MWh / t HRC | candidate/development |
| `HSM_REHEAT_FUEL_CARRIERS` | BFG, COG, BOFG, NG | n/a | eligible carriers | candidate/development |
| `HSM_DIRECT_CO2_MODE` | `derived_from_reheat_fuel_mix` | n/a | accounting mode | diagnostic policy |
| `HSM_FLEXIBILITY_CLASS` | `bounded_downstream_scheduling_asset` | n/a | class | diagnostic policy |

## 2026-07-16 Gate-2 Material-Conversion Evidence Resolution

The historical 1.10 value had no verified source locator. It represented a
broad combined material-loss proxy, not a measured IJmuiden HSM yield. Because
its basis is explicitly slab input per tonne hot-rolled coil, it must not also
contain liquid-steel-to-slab casting loss. In the active origin ledger the same
coefficient applies to endogenous BOF slab, endogenous EAF slab and imported
slab; no origin receives a different HSM yield.

The active Gate-2 development central is 1.06 t slab/t HRC, rounded from the
MER boundary reconciliation at the existing 1.05 DSP development conversion:

- MER material input: 6.8 Mt/y liquid steel + 0.6 Mt/y imported slab;
- MER final products: 5.5 Mt/y rolled coils + 1.5 Mt/y DSP rolls, with cutting
  losses already deducted from those product volumes;
- implied HSM input/output at DSP 1.05: `(7.4 - 1.5 * 1.05) / 5.5 = 1.05909`;
- the DSP 1.03-1.07 sensitivity range implies HSM 1.05364-1.06455;
- even assuming zero DSP material loss gives an HSM ceiling of 1.07273.

Two independent generic technical sources support a value below that MER
ceiling:

1. European Commission, *Reference Document on Best Available Techniques in
   the Ferrous Metals Processing Industry*, 2001, hot rolling sections
   A.3.1.3-A.3.1.5, reports hot-coil scale-loss reference 0.7% (0.5-2.0%) and
   finishing-loss reference 0.4% (0.0-1.6%). If combined conservatively as
   distinct loss categories, the reference ratio is about 1.011 and the sum of
   the reported upper ranges gives about 1.037. Locator:
   https://www.umweltbundesamt.de/system/files/medien/publikation/long/2490.pdf
2. JICA, steel-plant engineering report, Chapter 13, Table 13-10-1, specifies
   97.5% slab-to-hot-coil yield for both project stages, equivalent to
   1.02564 t slab/t hot coil. Locator:
   https://openjicareport.jica.go.jp/pdf/10466621_13.pdf

The 1.06 central remains a development boundary reconciliation, not a Tata
measurement. The wider 1.10 proxy is retained only for labelled historical
high-loss sensitivity. HSM material difference is an explicit internal
loss/scrap diagnostic and may not disappear into a residual supply term.

## 2026 Source Repair Update - Hot Rolling Energy Candidates

This update records reviewed public literature values for HSM/WBW electricity,
fuel and aggregate GHG sanity checks. It is a source-card repair only: the rows
below are not executable inputs, not Tata IJmuiden measurements, and not
thesis-approved values. The original articles were not locally inspected in this
repository during this repair, so source locators remain non-verified until a
later provenance pass.

| Parameter ID | Value / range | Unit | Original basis | Converted basis / derivation | Status label | Recommended model use | Source title, authors, year, URL/DOI | Locator status | Caveat |
|---|---:|---|---|---|---|---|---|---|---|
| `HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID` | 0.104 | MWh/t hot rolled steel | 0.104 kWh/kg hot rolled steel | 0.104 kWh/kg = 0.104 MWh/t | source_backed_candidate | development_input_candidate / sensitivity_range | Khalid et al. (2021), *Oxygen enrichment combustion to reduce fossil energy consumption and emissions in hot rolling steel production*, Journal of Cleaner Production 320, 128714, https://doi.org/10.1016/j.jclepro.2021.128714 | source_locator_not_verified_in_repo | ArcelorMittal North America hot mill / LCA context, not Tata WBW-specific; value_from_reviewed_research_note_not_locally_verified. |
| `HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID` | 1.268 | GJ/t hot rolled steel | 1.268 MJ/kg hot rolled steel | 1.268 MJ/kg = 1.268 GJ/t | source_backed_candidate | development_input_candidate / sensitivity_range | Khalid et al. (2021), DOI above | source_locator_not_verified_in_repo | Baseline natural-gas-fired pusher reheating furnace; Tata may use a WAG/NG mix; value_from_reviewed_research_note_not_locally_verified. |
| `HSM_GHG_T_PER_T_HRC_KHALID` | 0.113 | tCO2e/t hot rolled steel | 0.113 kg CO2-eq/kg hot rolled steel | 0.113 kg/kg = 0.113 t/t | source_backed_candidate | validation_target / aggregate sanity check | Khalid et al. (2021), DOI above | source_locator_not_verified_in_repo | Aggregate LCA/GHG value; do not add to fuel-explicit HSM combustion CO2; value_from_reviewed_research_note_not_locally_verified. |
| `HSM_OXYGEN_ENRICHMENT_FUEL_REDUCTION_SENS` | 19.6-26.8 | % natural gas reduction | Oxygen-enrichment cases in hot rolling furnace study | no conversion | sensitivity_only | future technology sensitivity only | Khalid et al. (2021), DOI above | source_locator_not_verified_in_repo | Not base case; avoid changing fuel technology in forecast-quality or C5 baseline comparisons. |
| `HSM_OXYGEN_ENRICHMENT_TOTAL_ENERGY_REDUCTION_SENS` | 15.1-20.7 | % total energy reduction | Oxygen-enrichment cases in hot rolling furnace study | no conversion | sensitivity_only | future technology sensitivity only | Khalid et al. (2021), DOI above | source_locator_not_verified_in_repo | Not base case; value_from_reviewed_research_note_not_locally_verified. |
| `HSM_OXYGEN_ENRICHMENT_GHG_REDUCTION_SENS` | 11.1-15.2 | % GHG reduction | Oxygen-enrichment cases in hot rolling furnace study | no conversion | sensitivity_only | future technology sensitivity only | Khalid et al. (2021), DOI above | source_locator_not_verified_in_repo | Not base case; value_from_reviewed_research_note_not_locally_verified. |
| `HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_CANDIDATE` | 0.104 | MWh/t HRC | Khalid hot mill electricity candidate | same as `HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID` | source_backed_candidate | development_input_candidate / sensitivity_range | Khalid et al. (2021), DOI above | source_locator_not_verified_in_repo | First-pass candidate only; do not promote until reconciled against MER downstream electricity/gas anchors and current HSM/WBW assumptions. |
| `HSM_REHEAT_FUEL_GJ_PER_T_HRC_CANDIDATE` | 1.268 | GJ/t HRC | Khalid hot mill fuel candidate | same as `HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID` | source_backed_candidate | development_input_candidate / sensitivity_range | Khalid et al. (2021), DOI above | source_locator_not_verified_in_repo | First-pass candidate only; do not promote until WAG/NG fuel boundary is reviewed. |
| `HSM_ELECTRICITY_LOWER_CONTEXT_ORCAJO` | >0.070 | MWh/t hot rolled steel | More than 70 kWh/t | >70 kWh/t = >0.070 MWh/t | generic_range | lower-bound sanity check | Orcajo et al. (2016), *Dynamic Estimation of Electrical Demand in Hot Rolling Mills*, IEEE Transactions on Industry Applications 52(3), 2714-2723, https://doi.org/10.1109/TIA.2016.2533483 | source_locator_not_verified_in_repo | Generic hot rolling demand context; value_from_reviewed_research_note_not_locally_verified. |
| `HSM_ELECTRICITY_TYPICAL_CONTEXT_ORCAJO` | approximately 0.080 | MWh/t hot rolled steel | Approximately 80 kWh/t | 80 kWh/t = 0.080 MWh/t | generic_range / context_only | validation/context | Orcajo et al. (2016), DOI above | source_locator_not_verified_in_repo | Context only, not executable base input. |
| `HSM_AUXILIARY_ELECTRICITY_SHARE_ORCAJO` | 0.25 | fraction of electrical energy | Auxiliary equipment around 25% of electrical energy | no conversion | context_only / sensitivity_only | split motors vs auxiliaries only if needed | Orcajo et al. (2016), DOI above | source_locator_not_verified_in_repo | Do not split HSM electricity unless a later plant-level electricity boundary requires it. |
| `HSM_ELECTRICITY_DYNAMIC_LOAD_NOTE` | true | context flag | rolling stands/coilers have dynamic loads | no conversion | context_only | source_card_repair_needed / deferred | Orcajo et al. (2016), DOI above | source_locator_not_verified_in_repo | HSM power can be highly dynamic, but do not create DA/mFRR flexibility without slab, thermal and product constraints. |

Keep earlier BAT/FMP and project-development ranges as sensitivities. This
repair does not retune `HSM_REHEAT_ENERGY_GJ_PER_T_HRC`, does not change
`HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC`, and does not add HSM/WBW market
flexibility.

## Hot-Charge Share Cap Candidate Evidence

`S4.4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch` adds
development-only candidate cap values for combined direct-hot and hot/warm HSM
slab charging:

| Parameter | Value | Unit | Status |
|---|---:|---|---|
| `HSM_HOT_CHARGE_SHARE_MAX_BASE` | 0.50 | share of total HSM slab input | development guardrail |
| `HSM_HOT_CHARGE_SHARE_MAX_HIGH` | 0.80 | share of total HSM slab input | development sensitivity |

Source registration:

- Schneider, Clemens & Lechtenbohmer, Stefan (2016). Industrial site energy
  integration - the sleeping giant of energy efficiency? Identifying site
  specific potentials for vertical integrated production at the example of
  German steel production. ECEEE Industrial Summer Study Proceedings,
  pp. 587-598. Wuppertal Institute.
- URL:
  `https://epub.wupperinst.org/frontdoor/deliver/index/docId/6912/file/6912_Schneider.pdf`
- Locator status: user-provided source interpretation; exact locator pending
  targeted provenance verification.

Interpretation used for development diagnostics only: Schneider &
Lechtenbohmer use a 50% hot-charging rate as a calculation example for
energy-saving potential, and indicate that direct hot charging/direct rolling
with strong synchronisation can reach around 85% hot charging. C5l_d therefore
uses 0.50 as a conservative modelling guardrail and 0.80 as a rounded
optimistic sensitivity. These are not Tata-measured values and are not
thesis-approved.

## Output Driver Policy

```text
HSM_OUTPUT_DRIVER_MODE = scale_public_downstream_anchors_to_active_liquid_steel_target
```

Raw MER/HSM public downstream volumes remain validation/context anchors. Active
C5l HSM/DSP/imported-slab drivers are scaled to the C5k active liquid-steel
target when used for development accounting. This avoids mixing a 6.75 Mt/y
active steel target with unscaled 7.2 or 6.8 Mt/y public context anchors.

## Context Anchors

Anchors are validation/reporting targets only and must not be used as hard
dispatch constraints.

| Configuration | Metric | Context value | Unit |
|---|---:|---:|---|
| C0/reference | MER liquid steel context | 7.2 | Mt/y |
| C0/reference | HSM rolled coils context | 5.4 | Mt/y |
| C0/reference | DSP rolls context | 1.5 | Mt/y |
| C1/Heracless | MER liquid steel context | 6.8 | Mt/y |
| C1/Heracless | HSM rolled coils context | 5.5 | Mt/y |
| C1/Heracless | DSP rolls context | 1.5 | Mt/y |
| C1/Heracless | imported slabs context | 0.6 | Mt/y |

## Derived Reporting Values

Derived values must be calculated from active development input rows:

- `HSM_slab_input = HSM_output * HSM_SLAB_INPUT_T_PER_T_HRC`
- `HSM_internal_loss_or_scrap = HSM_slab_input - HSM_output`
- `HSM_reheat_heat_GJ = HSM_output * HSM_REHEAT_ENERGY_GJ_PER_T_HRC`
- `HSM_reheat_heat_MWh = HSM_reheat_heat_GJ / 3.6`
- `HSM_rolling_electricity_MWh = HSM_output * HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC`

## Caveats

- Candidate only; not Tata-validated and not thesis-approved.
- No calibration to MER, Heracless, Athanasiadis, WAG electricity, or CO2 anchors.
- No direct WAG market valuation, WAG export revenue, product revenue, DA
  bidding, stochasticity, CVaR, mFRR, ETS objective steering, or CBAM.
- No free slab battery, unconstrained slab storage, slab-yard thermal model, or
  BF-to-BOF hot-metal buffer is introduced by this source card.
