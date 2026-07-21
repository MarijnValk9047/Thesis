from __future__ import annotations

import argparse

from steel.s4_4c5p_ay_anchor_boundary_closure import run_anchor_boundary_closure


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile an existing C1 annual anchor boundary contract.")
    parser.add_argument("--config", default=None, help="Optional closure YAML; source runs are read-only.")
    parser.add_argument("--output-root", default=None, help="Optional governed local run root.")
    args = parser.parse_args()
    kwargs = {}
    if args.config:
        kwargs["config_path"] = args.config
    if args.output_root:
        kwargs["output_root"] = args.output_root
    result = run_anchor_boundary_closure(**kwargs)
    print(result["run_directory"])
