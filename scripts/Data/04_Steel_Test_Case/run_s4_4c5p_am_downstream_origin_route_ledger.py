"""Run the C5 annual downstream origin-route ledger."""

from __future__ import annotations

from steel.s4_4c5p_am_downstream_origin_route_ledger import run_downstream_origin_route_ledger


if __name__ == "__main__":
    print(run_downstream_origin_route_ledger()["summary"])
