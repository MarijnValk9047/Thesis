# BOF / OSF Parameters Source Card

Status: candidate source-card memo, development-only.

Thesis usability: false.

This memo records a compact public/generic BOF/OSF parameter set for
development diagnostics in `S4.4c5j_BOF_OSF_minimal_parameterisation`. It is not
an approved executable thesis input table, not exact Tata truth, and not a
calibration target. Values may be migrated only into labelled development input
rows with explicit governance metadata, review caveats, and sensitivity
requirements.

## Base Interpretation

The BOF/OSF layer is represented as a production-coupled, batch-equivalent
accounting process:

```text
hot metal + scrap + oxygen + electricity
  -> BOF/OSF
  -> liquid steel + BOFG/oxygas + direct CO2 diagnostic
```

The activity basis is tonnes of liquid steel. If an existing modelbuilder uses
hot metal or route throughput as the internal process driver, C5j must report the
conversion basis rather than create a second free liquid-steel variable.

## Configuration-Specific Metallic Inputs

| Parameter | Value | Unit | Status |
|---|---:|---|---|
| `BOF_HOT_METAL_INPUT_T_PER_T_LS_C0` | 0.875 | t hot metal / t liquid steel | candidate/development |
| `BOF_SCRAP_INPUT_T_PER_T_LS_C0` | 0.208 | t scrap / t liquid steel | candidate/development |
| `BOF_HOT_METAL_INPUT_T_PER_T_LS_C1` | 0.824 | t hot metal / t liquid steel | candidate/development |
| `BOF_SCRAP_INPUT_T_PER_T_LS_C1` | 0.294 | t scrap / t liquid steel | candidate/development |

## Generic BOF/OSF Coefficients

| Parameter | Value | Unit | Status |
|---|---:|---|---|
| `BOF_OXYGEN_INPUT_NM3_PER_T_LS` | 55 | Nm3 O2 / t liquid steel | candidate/development |
| `BOF_OXYGEN_INPUT_KG_PER_T_LS` | 78.6 | kg O2 / t liquid steel | derived mass-basis diagnostic |
| `BOF_ELECTRICITY_MWH_PER_T_LS` | 0.0268 | MWh / t liquid steel | candidate/development |
| `BOF_BOFG_OUTPUT_NM3_PER_T_LS` | 75 | Nm3 BOFG / t liquid steel | candidate/development |
| `BOF_DIRECT_CO2_T_PER_T_LS` | 0.0825 | tCO2 / t liquid steel | candidate/development diagnostic |
| `BOFG_LHV_MJ_PER_NM3` | 8.6 | MJ/Nm3 | project-canonical WAG LHV |

Derived reporting values must be calculated from active input rows:

- `BOF_METALLIC_INPUT_T_PER_T_LS = hot_metal_per_t_LS + scrap_per_t_LS`
- `BOF_LS_YIELD_PER_T_METALLIC_INPUT = 1 / metallic_input_per_t_LS`
- `BOFG_MWH_PER_T_LS = BOF_BOFG_OUTPUT_NM3_PER_T_LS * BOFG_LHV_MJ_PER_NM3 / 3600`
- `BOF_HOT_METAL_SHARE = hot_metal / (hot_metal + scrap)`
- `BOF_SCRAP_SHARE = scrap / (hot_metal + scrap)`

## 2026 Source Repair Update - Bieda 2012 BOF LCI Candidates

This update records reviewed public BOF/OSF auxiliary fuel, electricity,
oxygen, by-product and aggregate CO2 candidates from Bieda (2012). It is a
source-card repair only. These values are not Tata IJmuiden measurements, not
thesis-approved values, and not executable inputs. The original article was not
locally inspected in this repository during this repair, so locators remain
non-verified. Volume terms preserve the source unit `m3`; do not relabel them
as `Nm3` or convert to energy without a reviewed LHV and normalization basis.

| Parameter ID | Value / range | Unit | Original basis | Converted basis / derivation | Status label | Recommended model use | Source title, authors, year, URL/DOI | Locator status | Caveat |
|---|---:|---|---|---|---|---|---|---|---|
| `BOF_NG_M3_PER_T_LS_BIEDA` | 6.36 | m3/t liquid steel | 10,671,997 m3 natural gas / 1,677,987 Mg steel | 10,671,997 / 1,677,987 = 6.36 m3/t | source_backed_candidate | sensitivity_range / auxiliary fuel candidate | Bieda (2012), *Life cycle inventory processes of the ArcelorMittal Poland (AMP) S.A. in Krakow, Poland - basic oxygen furnace steel production: A case study*, International Journal of Life Cycle Assessment 17, 463-470, https://doi.org/10.1007/s11367-011-0370-y | source_locator_not_verified_in_repo | Polish BOF gate-to-gate source, not Tata; may include plant boundary beyond converter reaction; value_from_reviewed_research_note_not_locally_verified. |
| `BOF_BFG_M3_PER_T_LS_BIEDA` | 0.45 | m3/t liquid steel | BFG input per tonne steel from Bieda LCI | source unit retained | source_backed_candidate | context/sensitivity | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Very small auxiliary term; source unit m3 retained. |
| `BOF_COG_M3_PER_T_LS_BIEDA` | 7.88 | m3/t liquid steel | COG input per tonne steel from Bieda LCI | source unit retained | source_backed_candidate | sensitivity_range / auxiliary fuel candidate | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Non-Tata auxiliary fuel candidate; do not force into Tata base without WAG boundary review. |
| `BOF_ELECTRICITY_MWH_PER_T_LS_BIEDA` | 0.02682 | MWh/t liquid steel | 45,003,611.3 kWh / 1,677,987 Mg steel | 45,003,611.3 / 1,677,987 = 26.82 kWh/t = 0.02682 MWh/t | source_backed_candidate | development_input_candidate / cross-check | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Aligns with current compact BOF electricity order of magnitude; still non-Tata. |
| `BOF_STEAM_KG_PER_T_LS_BIEDA` | 12.9 | kg/t liquid steel | BOF steam use per tonne steel from Bieda LCI | source unit retained | source_backed_candidate | sensitivity_range / optional utility demand | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Optional utility demand only; do not add steam demand without steam-network review. |
| `BOF_OXYGEN_M3_PER_T_LS_BIEDA_DERIVED` | 54.0 | m3 O2/t liquid steel | 90,611,298 m3 O2 / 1,677,987 Mg steel | 90,611,298 / 1,677,987 = 54.0 m3/t | source_backed_candidate | development_input_candidate / cross-check for existing 55-60 m3/t base | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Table formatting may conflict on air/oxygen; annual totals support 54.0 m3/t oxygen and 64.1 m3/t air. Use Nm3 only if the source explicitly states normal conditions. |
| `BOF_AIR_M3_PER_T_LS_BIEDA_DERIVED` | 64.1 | m3 air/t liquid steel | Annual air total / 1,677,987 Mg steel | derived from reviewed note | context_only | deferred unless air utility is modelled | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Context only; value_from_reviewed_research_note_not_locally_verified. |
| `BOF_DIRECT_CO2_T_PER_T_LS_BIEDA` | approximately 0.0825 | tCO2/t liquid steel | 138,377 Mg CO2 / 1,677,987 Mg steel | 138,377 / 1,677,987 = 0.0825 tCO2/t | source_backed_candidate | aggregate CO2 validation/sensitivity | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Do not add if BOFG carbon is counted at downstream combustion; use aggregate BOF counter or WAG-explicit carbon accounting, not both. |
| `BOF_SLAG_KG_PER_T_LS_BIEDA` | approximately 165 | kg/t liquid steel | 276,709.64 Mg slag / 1,677,987 Mg steel | 276,709.64 / 1,677,987 = 0.1649 t/t = 165 kg/t | source_backed_candidate | validation_target / material by-product check | Bieda (2012), DOI above | source_locator_not_verified_in_repo | By-product validation only unless a slag material balance is opened. |
| `BOF_GAS_CLEANING_SLUDGE_KG_PER_T_LS_BIEDA` | approximately 10.0 | kg/t liquid steel | 16,749 Mg sludge / 1,677,987 Mg steel | 16,749 / 1,677,987 = 0.00998 t/t = 10.0 kg/t | source_backed_candidate | deferred/detail | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Detail only; do not add residue accounting unless scope is opened. |
| `BOFG_OUTPUT_M3_PER_T_LS_BIEDA` | 50-80 | m3/t steel | BOF gas output range | source unit retained | source_backed_candidate | development_input_candidate / sensitivity_range | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Use source unit m3 unless normal conditions are explicitly verified. |
| `BOFG_COMPOSITION_BIEDA` | CO 55-80 vol%, average 72.5; H2 2-10 vol%, average 3.3; CO2 10-18 vol%, average 16.2; N2+Ar 8-26 vol%, average 8.0; density 1.32-1.38 kg/m3, average 1.33; LHV/HHV 7,000-10,000 kJ/m3 with table inconsistency | mixed | BOFG composition and calorific value table | no conversion | source_backed_candidate / sensitivity_range | source_card_repair_needed before replacing canonical factors | Bieda (2012), DOI above | source_locator_not_verified_in_repo | Project-canonical `BOFG_LHV_MJ_PER_NM3` remains unchanged unless explicitly reviewed; table average lower/upper calorific-value labels need verification. |

## Validation Anchors

Anchors are validation/reporting targets only and must not be used as hard
dispatch constraints.

| Configuration | Metric | Anchor | Unit |
|---|---|---:|---|
| C0 | BOF liquid steel output | 7.2 | Mt/y |
| C0 | hot metal input to BOF | 6.3 | Mt/y |
| C0 | scrap input to BOF | 1.5 | Mt/y |
| C1 retained BF-BOF | BOF liquid steel output | 3.4 | Mt/y |
| C1 retained BF-BOF | route BF-BOF LS including alloys | 3.5 | Mt/y |
| C1 retained BF-BOF | hot metal input to BOF | 2.8 | Mt/y |
| C1 retained BF-BOF | scrap input to BOF | 1.0 | Mt/y |

Derived BOFG, oxygen, electricity, and direct CO2 quantities are diagnostics
only unless later promoted by a reviewed source/input process.

## Carbon Accounting

C5j uses:

```text
BOF_CO2_MODE = aggregate_direct_diagnostic
```

`BOF_DIRECT_CO2_T_PER_T_LS` is a direct diagnostic/reporting counter. It is not
an ETS objective term in C5j. BOFG combustion CO2, if reported later, must remain
separate and diagnostic-only unless a reviewed no-double-counting convention is
implemented.

## Caveats

- Candidate only; not Tata-validated and not thesis-approved.
- No calibration to Athanasiadis, Heracless, Tata, MER, WAG electricity, or CO2
  anchors.
- No BOFG market valuation, export revenue, DA bidding, stochasticity, CVaR,
  mFRR, ETS objective steering, or product revenue.

## C1 Temporal-v2 Scrap-Origin Contract (2026-08-03)

The active C1 BOF recipe remains 0.294 t scrap/t liquid steel, corresponding
to approximately 1.0 Mt/y at the route anchor. Its demand is now covered
exactly by two origin-tagged physical flows:

```text
external_scrap_to_BOF + internal_scrap_to_BOF = BOF_scrap_demand
```

Together with the corresponding EAF flows, external scrap is capped at
1.3 Mt/y, internal reuse at 0.6 Mt/y and total site availability at 1.9 Mt/y.
Route allocation is endogenous, but every tonne has one origin and one route.
Only external scrap receives represented procurement cost. Internal reuse is
not a free unbounded supply: it draws from the shared 0.6-Mt/y source. Any
future explicit caster/HSM/DSP scrap-generation link must replace, rather than
duplicate, that internal source. ISO 14021/WSA labels remain reporting
classifications and do not create another physical supply.
