# C5 24-hour WAG Runtime Profile

This stage separates model-build time from solve time and enforces an external
wall-clock guard around each solve. The full retained-route WAG case has a
maximum of 300 seconds. A timeout is a computational diagnostic only: no
dispatch, residual or anchor result may be inferred from it.

The profile separates C1-only solves from C0-only solves. It compares the
simple C1 DRP/EAF case, the retained BF-BOF route with and without WAG, and
the C0 WAG layer with fixed versus flexible binary schedules. This isolates
whether runtime comes from the retained physical route, WAG balances, or the
unfixed C0 binary schedule.
