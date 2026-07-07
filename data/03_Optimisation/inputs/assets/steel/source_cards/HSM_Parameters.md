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
| `HSM_SLAB_INPUT_T_PER_T_HRC` | 1.10 | 1.07-1.15 | t slab / t HRC | candidate/development |
| `HSM_REHEAT_ENERGY_GJ_PER_T_HRC` | 1.35 | 1.2-1.5 | GJ / t HRC | candidate/development |
| `HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC` | 0.070 | 0.028-0.111 | MWh / t HRC | candidate/development |
| `HSM_REHEAT_FUEL_CARRIERS` | BFG, COG, BOFG, NG | n/a | eligible carriers | candidate/development |
| `HSM_DIRECT_CO2_MODE` | `derived_from_reheat_fuel_mix` | n/a | accounting mode | diagnostic policy |
| `HSM_FLEXIBILITY_CLASS` | `bounded_downstream_scheduling_asset` | n/a | class | diagnostic policy |

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
