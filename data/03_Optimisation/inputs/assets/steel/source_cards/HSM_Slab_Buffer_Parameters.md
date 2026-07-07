# HSM Slab Buffer Parameters Source Card

Status: candidate source-card memo, development-only.

Thesis usability: false.

This memo records the compact slab age-bucket buffer and charge-specific HSM
reheating candidate set used by
`S4.4c5l_c_HSM_slab_age_bucket_buffer_and_charge_reheat`. It is not an approved
executable thesis input table, not exact Tata truth, and not a calibration
target. Values may be migrated only into labelled development input rows with
explicit governance metadata, caveats, and sensitivity requirements.

## Modelling Scope

The C5l_c layer represents:

```text
liquid steel to HSM route
  -> caster
  -> hot slab age buckets
  -> cold slab yard
  -> reheating
  -> HSM/WBW
  -> hot rolled coil
```

DSP remains a direct/liquid route and bypasses the slab yard. The active HSM
material conversion remains `HSM_SLAB_INPUT_T_PER_T_HRC = 1.10`; the possible
`HSM_yield = 1.0` simplification is deferred as sensitivity material only.

## Buffer Candidate Values

| Parameter | Base | Unit | Status |
|---|---:|---|---|
| `SLAB_BUFFER_ENABLED` | true | boolean | development assumption |
| `SLAB_BUFFER_MODE` | `age_bucket_hot_cold_slab_yard` | mode | development assumption |
| `SLAB_STORE_CAPACITY_TOTAL_T` | 25,000 | t slab | candidate precedent |
| `INITIAL_COLD_SLAB_INVENTORY_T` | 12,500 | t slab | development assumption |
| `INITIAL_HOT_SLAB_INVENTORY_T` | 0 | t slab | development assumption |
| `TERMINAL_TOTAL_SLAB_INVENTORY_EQUALS_INITIAL` | true | boolean | development assumption |
| `TERMINAL_HOT_SLAB_INVENTORY_ZERO` | true | boolean | development assumption |
| `AGE_BUCKET_WIDTH_H` | 1 | h | development assumption |
| `CASTER_TO_AGE0_LAG_H` | 1 | h | development assumption |
| `CASTER_YIELD_TO_SLAB` | 1.0 | t slab/t cast steel | development assumption |

The 25,000 t slab-store capacity is a modelling precedent/candidate value. It
must not be presented as proven Tata IJmuiden capacity without later review.

## Reheat Candidate Values

| Parameter | Base | Unit | Status |
|---|---:|---|---|
| `REHEAT_DHCR_GJ_PER_T_SLAB` | 0.335 | GJ/t slab | generic candidate |
| `REHEAT_HCR_GJ_PER_T_SLAB` | 0.878 | GJ/t slab | generic candidate |
| `REHEAT_CCR_GJ_PER_T_SLAB` | 1.338 | GJ/t slab | generic candidate |
| `CASTER_AUX_ENERGY_GJ_PER_T_CAST_STEEL` | 0.06 | GJ/t cast steel | diagnostic only |
| `HOT_ROLLING_COLD_CHARGE_ENERGY_CHECK_GJ_PER_T_HRC` | 1.55 | GJ/t HRC | validation/plausibility only |

The DHCR/HCR/CCR values are generic literature-style candidates, not
Tata-specific values. Reheat MWh are thermal/LHV-equivalent, not electricity.

## Caveats

- Candidate only; not Tata-validated and not thesis-approved.
- No calibration to MER, Heracless, Athanasiadis, WAG electricity, or CO2 anchors.
- No Sinter, PEFA, product revenue, DA bidding, stochasticity, CVaR, mFRR, ETS
  objective steering, WAG direct valuation, or WAG export revenue is introduced.
- The buffer has finite capacity and terminal inventory policy. It is not a free
  slab battery or unconstrained storage asset.
- Hot/cold nonlinear temperature decay, grade/width/thickness sequencing, and
  Wobbe-index/burner-quality constraints are deferred.
