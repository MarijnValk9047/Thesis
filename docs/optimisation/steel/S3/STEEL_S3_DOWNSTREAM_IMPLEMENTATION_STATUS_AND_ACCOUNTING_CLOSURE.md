# S3 Downstream Implementation Status And Accounting Closure

## Purpose

This audit checks whether downstream/end-processing assets were already implemented after the `S2.12` downstream and WAG boundary correction.

Conclusion: downstream continuation existed as S2.12 governance and S3 boundary policy, but it was not executable downstream energy/cost accounting and was not present in the C0/C1 fixed profiles. S3 now adds accounting-only downstream driver rows. It does not add scheduling, storage, DA price response, product revenue, cost accounting, or ETS logic.

## Status Found

The S2.12 downstream register contains C0 and C1 continuation rows for:

- secondary metallurgy;
- casting;
- slab handling and transfer;
- reheating;
- HSM or downstream rolled-product boundary;
- ASU and oxygen interface;
- residual throughput-coupled auxiliary load placeholder.

Those rows were governance and boundary eligibility surfaces. They did not create S3 executable accounting equations, profile rows, or diagnostic outputs.

The S3.0d plant-boundary gate explicitly kept downstream electricity, auxiliary loads, residual site load, complete heat/steam sinks, and complete direct emissions outside the current component diagnostics.

## Accounting Drivers Added

The governed fixed profiles now carry hourly accounting drivers for C0 and all three C1 scenarios:

- `secondary_metallurgy_output_proxy`;
- `continuous_casting_liquid_steel_input`;
- `continuous_casting_slab_output_proxy`;
- `slab_handling_transfer_proxy`;
- `reheating_or_hot_charge_throughput_proxy`;
- `hot_strip_mill_throughput_proxy`;
- `finished_product_boundary_proxy`;
- `oxygen_demand_auxiliary_driver`;
- `residual_downstream_auxiliary_boundary_driver`.

These rows are throughput-coupled to the same-output liquid-steel/slab/product proxy. They are marked as `accounting_driver` rows and `thesis_usability=false`.

## What This Does Not Implement

The closure does not implement:

- secondary-metallurgy scheduling;
- casting constraints;
- slab yard optimisation;
- slab storage or battery-like behaviour;
- hot/cold charging optimisation;
- reheating-furnace dispatch;
- HSM rolling binaries;
- product mix;
- product revenue;
- DA prices, bidding, settlement, tariffs, gross ETS, or route optimisation.

Missing downstream coefficients remain missing. They are not converted into zero demand.

## Registers

The audit status is stored in:

- `s3_downstream_implementation_status_register.csv`;
- `s3_downstream_accounting_boundary_register.csv`.

Readiness flags were added to:

- `s3_cost_da_integration_readiness_register.csv`;
- `s3_c1_scenario_wag_readiness_register.csv`;
- `s3_wag_runtime_input_closure_register.csv`.

Driver-level readiness can now be true. Downstream electricity, heat/steam, full process logic, cost, and DA readiness remain false.

## C0 And C1 Implications

C0 WAG mechanics remain unchanged. C1 route shares and selected DRP/EAF coefficients remain unchanged.

C1 component diagnostics still remain component-boundary diagnostics. Zero residual component grid import still means only that represented DRP/EAF component electricity is covered by potential WAG offset. It is not plant-level grid import, cost, revenue, or DA exposure.

## Remaining Cost/DA Blockers

Before S3 cost or DA integration, the model still needs:

- downstream electricity coefficients;
- reheating and broader heat/steam boundary coefficients;
- ASU/oxygen electricity coefficients;
- residual auxiliary or site-load policy;
- downstream emissions policy;
- product-output boundary policy;
- static cost inputs and ETS/tariff policy after boundary closure.

## Validation

Focused tests verify that downstream drivers exist in C0 and C1 profiles, same-output and route shares are unchanged, DRP/EAF coefficients are unchanged, hidden zero energy coefficients are not introduced, and cost/DA readiness remains false.
