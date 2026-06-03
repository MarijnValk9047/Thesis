# Performance And Cache Rules

## Scope

These rules govern engineering performance measures. They do not authorise methodological shortcuts.

Selected-week split governance is defined separately in `docs/optimisation/SELECTED_WEEK_POLICY.md`. Cache and run infrastructure must preserve whether a run used validation selected weeks, test selected weeks, or the deprecated legacy mixed file.

## Cacheable objects

The first cache layer should target reusable input slices:

- scenario slices filtered to a selected local-date window;
- derived actual-price market slices taken from the same scenario artifact;
- small registries such as origin-level completeness summaries.

Later layers may cache:

- perfect-foresight benchmark results;
- price-insensitive benchmark results;
- validated day-level solve outputs.

## Cache key rules

An input-slice cache key must include:

- artifact identifier;
- selected local-date window or selected-week labels;
- selected-week source file when selected-week mode is used;
- horizon mode;
- granularity;
- source fingerprints for config, scenario catalog, and source artifact.

The experiment fingerprint should additionally include:

- strategy set;
- solver settings;
- bid grid;
- risk settings;
- output policy;
- methodological approximation labels.

## Stale-cache invalidation

A cache entry is stale when the current source fingerprints do not match the source fingerprints saved in the cache manifest.

At minimum, compare:

- config file fingerprint;
- scenario catalog fingerprint;
- selected-week config fingerprint when selected-week mode is used;
- source artifact fingerprint.

## Runtime profiling minimum

Every reusable runner should record:

- `load`
- `build`
- `solve`
- `write`

Additional sub-stages are allowed, but these four are the minimum contract.

## Solver log policy

Do not keep solver logs for every optimal bulk solve.

Keep them when:

- the solve failed;
- the solve is an explicitly requested audit day;
- the run is a debugging or audit workflow where the user asked for solver-level inspection.

## What is engineering optimisation

Allowed engineering optimisation examples:

- caching resolved input slices;
- avoiding repeated raw-file reads in nested loops;
- reusing deterministic benchmark outputs when the exact same inputs and settings were already solved;
- disabling unnecessary figure generation in bulk runs;
- preserving only the required outputs for the chosen output policy.

These do not change the thesis method.

## What is not engineering optimisation

The following change the method and must be labelled as methodological approximations:

- fewer scenarios than the baseline scenario set;
- altered scenario probabilities;
- looser MIP gap than the baseline;
- reduced bid grid;
- binary relaxation;
- shorter horizon than the claimed design;
- altered settlement or clearing rules.
