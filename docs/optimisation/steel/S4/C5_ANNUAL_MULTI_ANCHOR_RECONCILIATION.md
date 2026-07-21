# C5 Annual Multi-Anchor Reconciliation

## Purpose

`S4.4c5p_aw` is the single diagnostic view of the existing C1 annualised
representative-week physical runs. It compares production, electricity, WAG
and explicitly represented fuel CO2 anchors without changing dispatch,
allocating a residual, or treating an anchor as a constraint.

## Target policy

- `within_7_5pct_target` applies only when the absolute residual share is
  strictly below 7.5% for a boundary-comparable anchor.
- `within_10pct_review` requires a documented explanation before any further
  sensitivity is considered.
- `outside_10pct` requires a boundary or source-chain investigation, not
  automatic parameter tuning.

Each anchor row records its numerator definition, denominator definition,
site/process boundary, scaling status, score status and exclusion reason. The
rule applies only to rows whose numerator, denominator and boundary are
explicitly comparable. Residual electricity and NG remain visible reporting
quantities; they do not have to be zero.

## Athanasiadis Figure 91

The user-supplied Figure 91 records Athanasiadis model-versus-real directions:
CO2 `+9.06%`, total site NG `+7.11%`, coal `-7.68%`, and WAG electricity
generation `+9.72%`. The figure is a model-precedent directional check, not a
numeric Tata anchor or an optimisation target.

Consequently, C5p_aw records it separately. A direction can be compared only
after the C1 metric has the same total-site boundary. Current Mode-B fuel CO2,
named NG and represented internal WAG-electricity offset do not meet that
condition.

## WAG interpretation

The carrier table reports BFG, COG and BOFG separately against the existing
C1 generator-table context. It cannot enforce the context mix. A material
difference must be traced through generation, mandatory process self-use,
HSM/PEFA, boilers, generators and carrier-specific flare before any source
range sensitivity is proposed.

The published `14.6 PJ/y` C1 generator-plus-flare total includes a `4.1 PJ/y`
named NG context. Because generator NG has no source-backed hourly allocation
in the physical model, that total is not scored. The derived WAG-only `10.6
PJ/y` context is retained as the carrier reconciliation check.

## Explicit exclusions

- no aggregate or mixed WAG physical allocation;
- no invented WAG/NG split or Wobbe model;
- no residual electricity or NG input;
- no full-site Scope 1 or ETS claim;
- no economic, DA or sensitivity optimisation.
