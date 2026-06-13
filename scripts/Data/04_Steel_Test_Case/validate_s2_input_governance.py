from __future__ import annotations

import argparse
import json
from pathlib import Path

from steel.config import load_config
from steel.governance import (
    dry_run_validate_input_governance,
    load_s2_candidate_mapping,
    load_s2_schema,
)


DEFAULT_CONFIG = Path(__file__).resolve().parent / "configs" / "candidate_review_toy_parse_only.yaml"
DEFAULT_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_schema"
DEFAULT_MAPPING_ROOT = Path(__file__).resolve().parents[3] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_mapping"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run validator for steel S2.3 input governance artifacts.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--schema-root", type=Path, default=DEFAULT_SCHEMA_ROOT)
    parser.add_argument("--mapping-root", type=Path, default=DEFAULT_MAPPING_ROOT)
    args = parser.parse_args()

    config = load_config(args.config)
    schema_bundle = load_s2_schema(args.schema_root)
    mapping_bundle = load_s2_candidate_mapping(args.mapping_root)
    payload = dry_run_validate_input_governance(
        config=config,
        schema_bundle=schema_bundle,
        mapping_bundle=mapping_bundle,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
