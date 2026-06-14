from __future__ import annotations

import argparse
import json
from pathlib import Path

from steel.config import load_config
from steel.governance import (
    dry_run_validate_input_governance,
    load_s2_approved_model_input,
    load_s2_candidate_mapping,
    load_s2_candidate_review,
    load_s2_schema_alignment,
    load_s2_schema,
)


DEFAULT_CONFIG = Path(__file__).resolve().parent / "configs" / "candidate_review_toy_parse_only.yaml"
DEFAULT_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_schema"
DEFAULT_MAPPING_ROOT = Path(__file__).resolve().parents[3] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_mapping"
DEFAULT_REVIEW_ROOT = Path(__file__).resolve().parents[3] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
DEFAULT_APPROVED_INPUT_ROOT = Path(__file__).resolve().parents[3] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run validator for steel S2 input governance artifacts.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--schema-root", type=Path, default=DEFAULT_SCHEMA_ROOT)
    parser.add_argument("--mapping-root", type=Path, default=DEFAULT_MAPPING_ROOT)
    parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    parser.add_argument("--alignment-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    parser.add_argument("--approved-input-root", type=Path, default=DEFAULT_APPROVED_INPUT_ROOT)
    args = parser.parse_args()

    config = load_config(args.config)
    schema_bundle = load_s2_schema(args.schema_root)
    mapping_bundle = load_s2_candidate_mapping(args.mapping_root)
    review_bundle = load_s2_candidate_review(args.review_root)
    alignment_bundle = load_s2_schema_alignment(args.alignment_root)
    approved_input_bundle = load_s2_approved_model_input(args.approved_input_root)
    payload = dry_run_validate_input_governance(
        config=config,
        schema_bundle=schema_bundle,
        mapping_bundle=mapping_bundle,
        review_bundle=review_bundle,
        alignment_bundle=alignment_bundle,
        approved_input_bundle=approved_input_bundle,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
