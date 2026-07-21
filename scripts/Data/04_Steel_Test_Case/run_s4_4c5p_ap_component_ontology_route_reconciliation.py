"""Run the C5 component-ontology and bounded route reconciliation stage."""

from __future__ import annotations

from steel.s4_4c5p_ap_component_ontology_route_reconciliation import run_component_ontology_route_reconciliation


def main() -> int:
    result = run_component_ontology_route_reconciliation()
    print(result["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
