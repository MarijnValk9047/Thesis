# Generic Reserve Feasibility Interface Design v1

## Purpose

This note records the current `mFRR` capacity-feasibility proxy in the hydrogen test case and defines a generic interface for later reserve-feasibility constraints that can extend to a steel-plant process graph.

This is a design note only. No activation model, settlement model, or full asset-graph reserve formulation is added here.

## Current `mFRR` capacity-feasibility logic

Current reserve direction is represented on the **load side**:

- `Up` reserve means **reducing electricity consumption** on activation.
- `Down` reserve means **increasing electricity consumption** on activation.

In the current Pyomo model, reserve capacity is constrained mainly by the scheduled electrical operating point:

- `Up_capacity <= scheduled_site_load`
- `Down_capacity <= max_site_load - scheduled_site_load`

where scheduled site load is the sum of the electrolyser and compressor electrical load in the current interval, and max site load is the electrolyser nominal power plus compressor maximum power.

The current capacity-only `mFRR` path also enforces:

- integer MW offered capacity;
- 1 MW minimum when a bid is selected;
- daily bid-selection structure from the repaired Dutch incident-reserve capacity export.

What is **not** currently enforced in reserve-feasibility space:

- output absorption feasibility for extra production under `Down` activation;
- downstream process availability;
- intermediate-buffer saturation under activation;
- recovery feasibility after `Up` activation;
- rolling production-target feasibility under activation;
- activation settlement, sanctions, or MARI energy logic.

### Consequence already visible in rolling-target diagnostics

Loose rolling-target cases can still select positive `Down` capacity at zero scheduled production, because `Down` is currently tied only to unused electrical headroom. The model does **not** yet ask whether extra activated output can be absorbed by production credit, storage, or downstream process capacity.

## Generic reserve-feasibility concept

Reserve feasibility should eventually be modeled as the intersection of:

1. electrical flexibility;
2. asset nameplate and ramp limits;
3. process-output feasibility;
4. intermediate storage or buffer feasibility;
5. downstream process capacity;
6. recovery feasibility after activation;
7. production-target feasibility;
8. grid import/export limits;
9. market and settlement obligations.

A future-proof interface should be phrased in generic plant terms:

```yaml
assets:
  - asset_id
    asset_type
    electric_power_min_mw
    electric_power_max_mw
    ramp_up_mw_per_interval
    ramp_down_mw_per_interval
    production_output_id
    output_rate_per_mwh
    can_increase_load_for_down_reserve
    can_reduce_load_for_up_reserve

buffers:
  - buffer_id
    material_id
    capacity_quantity
    initial_quantity
    min_quantity
    max_inflow_per_interval
    max_outflow_per_interval
    holding_cost
    terminal_value_mode

process_links:
  - from_asset_or_buffer
    to_asset_or_buffer
    material_id
    max_flow_per_interval
    conversion_ratio
    transport_delay_intervals

reserve_feasibility:
  direction_sign_convention
  require_output_absorption_for_down_reserve
  require_recovery_for_up_reserve
  conservative_proxy_mode
```

This keeps the hydrogen mapping simple now, while allowing later extension to EAF, DRI, casting, rolling, intermediate buffers, and downstream bottlenecks.

## Direction-specific conservative proxy

Before full activation modeling, the smallest conservative proxy should remain direction-specific.

For flexible-load assets:

```text
Up_capacity[t] <= scheduled_load[t] - minimum_safe_load[t]
```

and additionally `Up` should later be checked against production or recovery feasibility.

For `Down`:

```text
Down_capacity[t] <= unused_load_headroom[t]
```

and also:

```text
Down_capacity[t] * activation_duration_hours * output_rate
<= remaining_inventory_or_buffer_headroom[t]
```

If a direct quantity-based proxy is awkward, an equivalent conservative converted-MW cap can be used:

```text
Down_capacity[t] <= buffer_headroom_converted_to_mw[t]
```

### Current hydrogen mapping

For the hydrogen test case, the smallest conservative next step is:

- keep `Up` linked to reducible scheduled load;
- cap `Down` not only by electrical headroom, but also by remaining hydrogen production-credit or inventory headroom under rolling mode.

That is still a proxy, but it closes the current false-positive case where idle load can offer `Down` reserve even when no extra hydrogen can be absorbed.

## Future-proof implementation path

### Phase 1

- document current sign convention and current proxy;
- no model change.

### Phase 2

- add a generic `reserve_feasibility_proxy` config branch;
- map the current hydrogen case into generic asset/buffer terms;
- no full production-network reserve model yet.

### Phase 3

- implement a conservative `Down` reserve cap using remaining production-credit or buffer headroom;
- preserve current behaviour via config switch;
- rerun the rolling-target `mFRR` overlay.

### Phase 4

- generalise to an asset/process/buffer graph for the steel plant;
- include downstream bottlenecks and intermediate storage;
- still avoid a full activation scenario tree unless clearly needed.

## Acceptance criteria for the next implementation

The next implementation should ensure:

- the load-side `Up`/`Down` sign convention is explicit;
- `Up` and `Down` use direction-specific feasibility limits;
- `Down` cannot be offered from idle load unless extra output or state change can be absorbed;
- production-credit or inventory caps are respected under potential `Down` activation;
- rolling production targets remain satisfied;
- integer MW bids remain unchanged;
- v2 `EUR/MW/ISP x contract_isp_count` capacity-revenue scaling remains unchanged;
- no activation settlement, sanctions, MARI, or 4-hour products are introduced.

## Current implementation status

A first conservative `Down` reserve-feasibility proxy is now implemented behind a config switch:

- `reserve_feasibility_proxy.enabled`
- `reserve_feasibility_proxy.mode = conservative_output_absorption`
- `reserve_feasibility_proxy.down_output_absorption_source = rolling_production_credit_headroom`

Current hydrogen mapping:

- `Down` remains capped by unused electrical headroom;
- in rolling-target mode, `Down` is also capped by the remaining production-credit or inventory headroom converted to MW-equivalent activation room.
- `Up` can now also be capped by rolling future recoverable production headroom when the combined conservative recovery mode is enabled.

This keeps the interface generic while using the current hydrogen production-credit headroom as the first absorption proxy.

Still out of scope:

- full activation modelling;
- settlement, sanctions, MARI, and 4-hour products.
