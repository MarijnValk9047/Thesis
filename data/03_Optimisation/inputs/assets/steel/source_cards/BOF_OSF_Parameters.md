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
