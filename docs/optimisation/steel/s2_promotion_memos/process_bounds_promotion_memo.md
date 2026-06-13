# Process Bounds Promotion Memo

## Category Purpose In S2

`process_bounds` define throughput limits or candidate envelopes for `BF`, `BOF`, `DRP`, `EAF`, and downstream sinks.

## Evidence Status

Current evidence is a mix of:

- annual public anchors;
- annual-to-hourly methodology rows;
- generic technology ranges.

No approved hourly bound exists.

## Unit Conventions

- annual anchors: `Mt/y`
- translation methods: method rows, not executable units
- future executable target unit: typically `tonnes_per_hour`

## Sign Conventions

Bounds are positive magnitudes. They are not signed balance coefficients.

## Model Role

- candidate numerical model input later;
- methodology support now;
- validation anchor support now.

## Approval Blockers

- annual values are not hourly caps;
- availability and utilisation assumptions are not frozen;
- continuity-driven versus batch-equivalent treatment is not frozen per asset.

## Thesis-Usability Requirements

- explicit annual-to-hourly method;
- reviewed unit conversion;
- documented conservative versus central envelope choice;
- source review complete.

## Misuse Red Flags

- using annual route values as hourly maxima;
- using average throughput as online maximum;
- presenting translation-method rows as approved capacities.
