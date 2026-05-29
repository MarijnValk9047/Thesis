# Selected Week Policy

## Status

As of `2026-05-28`, selected-week governance is split into separate official validation and test configuration files:

- `scripts/Data/03_Hydrogen_Test_Case/configs/selected_validation_weeks.yaml`
- `scripts/Data/03_Hydrogen_Test_Case/configs/selected_test_weeks.yaml`

The old mixed file remains only as a deprecated compatibility artifact:

- `scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks.yaml`

Its archived pre-split contents are preserved at:

- `scripts/Data/03_Hydrogen_Test_Case/configs/legacy_selected_weeks_20260528.yaml`

## Policy

- Validation selected weeks are the only official selected-week inputs allowed for model, scenario, and CVaR policy selection.
- Test selected weeks are reserved for frozen-policy out-of-sample evaluation and reporting.
- Future selected-week runners should point explicitly to the split file that matches their role.
- Mixed selected-week files must not be used for new official validation/test evidence.
- The intended regime taxonomy is:
  - `typical_summer`
  - `typical_winter`
  - `high_volatility`
  - `high_price`
- `typical` means closest to seasonal median price behaviour under exact common support. It does not mean lowest volatility.
- If a split has no eligible week for a required target season, the split file must mark the fallback explicitly.
- Current validation exception:
  - no exact-common-support validation `typical_winter` week exists for LEAR Strict / LEAR FS3 / XGBoost FS3;
  - `2024-09-16` to `2024-09-22` is therefore labelled `winter_proxy`;
  - `winter_proxy` is not valid for seasonal winter claims;
  - `winter_proxy` is allowed only for runtime, debug, and common-support checks unless separately justified.

## Provenance basis

The split files are derived from the common-support selected-week policy already documented in:

- `scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks_common_support.yaml`
- `scripts/Data/03_Hydrogen_Test_Case/docs/selected_week_registry_common_support.csv`

These official split files preserve exact-common-support provenance while separating validation and test use so later claims remain methodologically clean.

## Legacy-run classification

Legacy runs that referenced `selected_weeks.yaml` remain valid as:

- exploratory runs;
- debugging runs;
- development-stage integration runs.

They are not official validation/test evidence unless rerun under the split selected-week policy.

Additional rule:

- old test-period runs must not be used for parameter tuning claims.

## Reporting implication

When a historical run used `selected_weeks.yaml`, label it explicitly as `legacy_mixed_selected_weeks` or equivalent wording in audit and reporting notes. Do not present it as official split-policy evidence.
