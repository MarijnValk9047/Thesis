# Production Targets Promotion Memo

## Category Purpose In S2

`production_targets` define what the deterministic fixed-target model is required to deliver.

## Evidence Status

Current rows are annual public anchors or route-level validation targets.

They are not approved executable production targets.

## Unit Conventions

- current public anchors: `Mt/y`
- current toy scaffold executable target: toy-only local run quantity
- future executable target must match the configured optimisation horizon explicitly

## Sign Conventions

Production targets are positive delivery quantities.

## Model Role

- validation target now;
- candidate input policy later;
- not yet approved executable constraint.

## Approval Blockers

- annual public anchors are not dispatch-period targets;
- target-policy choice is separate from public validation anchors;
- route targets can be validation-only even when site targets are later executable.

## Thesis-Usability Requirements

- explicit target-policy decision;
- horizon-aligned unit basis;
- reviewed distinction between validation anchor and active model target.

## Misuse Red Flags

- converting annual planning volumes into hidden daily targets;
- using route-level validation anchors as hard route constraints;
- describing validation anchors as approved operating commitments.
