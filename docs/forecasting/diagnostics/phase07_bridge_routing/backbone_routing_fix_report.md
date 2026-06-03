# Backbone Routing Fix Report

- Scope: diagnostic only, no substantive method change applied.
- Tiny-safe checks performed: path/column/timestamp routing verified; exporter bridge path resolved correctly to observed run directory.
- Result: remaining missingness is primarily endogenous lag availability under the currently routed observed-run bridge.
- Proposed (not applied) method change for approval: route LEAR_STRICT exporter to phase07-style bridged hourly NL backbone or rebuild observed bridge with equivalent complete-hour rule.
- Expected impact estimate (strict matrix overlap): +77.88 percentage points.
