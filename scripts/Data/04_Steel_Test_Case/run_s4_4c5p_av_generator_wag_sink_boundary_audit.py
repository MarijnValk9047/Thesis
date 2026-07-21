from __future__ import annotations

import argparse
from pathlib import Path

from steel.s4_4c5p_av_generator_wag_sink_boundary_audit import run_generator_wag_sink_boundary_audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the read-only C1 generator/WAG-sink boundary audit.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--source-run", type=Path, default=None)
    args = parser.parse_args()
    kwargs = {}
    if args.run_id:
        kwargs["run_id"] = args.run_id
    if args.source_run:
        kwargs["source_run"] = args.source_run
    print(run_generator_wag_sink_boundary_audit(**kwargs))
