# C5 Anchor Boundary Closure

`S4.4c5p_ay` compiles the feasible C1 MER-boundary case and records the
all-endogenous 6.75-Mt/y stress case separately.  The latter must be reported
as infeasible when the exact quota cannot close; it is never silently replaced
by an imported-slab case.  The stage does not allocate residual energy, tune a
parameter, or create a second WAG controller.

The stage extends the C5p_aw anchor contract with a numerator, denominator,
site/process boundary, scaling status, score status and exclusion reason for
every compared row.  A row is close only where its boundary is comparable and
its absolute residual share is strictly below 7.5 percent.

## Physical boundary rules

- BFG, COG and BOFG remain separate physical carriers and are reconciled only
  through C5p_o-compatible carrier ledgers.
- A difference between the historical C5p_m balance and an integrated run is
  logged as an activity/controller-boundary mismatch, never as a WAG-factor
  target.
- Gross electricity equals internal generator offset plus net import only for
  the represented process boundary.  Remaining site electricity stays visible
  as a reporting residual.
- Named NG is a common-LHV reporting subtotal; full-site NG stays residual.
- Mode-B explicit fuel CO2 excludes aggregate process counters and remains
  separate from Scope-1 context.
- Imported slab may feed HSM only in the explicit MER case.  It receives no
  upstream energy, WAG, NG or direct-fuel CO2.

## Gate

This stage can support a later cost-design decision only after at least four
boundary-comparable anchor families are individually below 7.5 percent, all
physical guardrails pass, and no residual has become an input or allocation.

## Current result

- The exact-quota all-endogenous C1 stress case has no accepted solution.
- The C1 MER-boundary case reaches 6.75 Mt/y with 0.6 Mt/y imported slab to
  HSM/WBW, zero origin-balance residual and zero imported upstream site energy,
  WAG, NG or direct-fuel CO2.
- The represented generator-WAG-plus-flare subtotal is within 7.5% of its
  comparable context anchor.  Site electricity, full-site NG and Scope 1 remain
  visible but non-comparable coverage residuals.

## Bounded electricity sensitivity screen

The C1 `mer_site_product` quota run was screened with only two separately
traceable electricity candidates. Neither was migrated to executable base
inputs.

| Case | Gross electricity (TWh/y) | Official site-electricity residual | Interpretation |
| --- | ---: | ---: | --- |
| baseline | 3.584 | -27.51% | represented-process boundary only |
| EAF secondary metallurgy (31 kWh/t LS) | 3.688 | -25.41% | source-separated from EAF arc electricity |
| HSM rolling candidate (104 kWh/t HRC) | 3.781 | -23.54% | generic hot-mill candidate; non-Tata locator remains pending |
| combined case | 3.884 | -21.44% | best screened case; still outside the 7.5% target |

All cases retain the 6.75-Mt/y final-product quota, material/origin guardrails
and carrier-specific WAG balance. WAG generator-plus-flare remains -6.97%
against its comparable context anchor in every case, because these electricity
levers do not alter WAG generation or allocation.

The screen does **not** justify another arbitrary electricity-coefficient
increase. The remaining gap is a visible site-boundary coverage gap. The next
physical check is EAF off-gas steam recovery: it is source-carded as
reporting-only at a 16-bar interface and cannot feed the current 15-bar bridge
until pressure/enthalpy treatment and no-double-counting are specified.
