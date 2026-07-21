from __future__ import annotations

import argparse

from steel.s4_4c5p_az_wag_activity_basis_audit import run_wag_activity_basis_audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit C1 WAG activity/controller-basis differences.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--active-run-id", default=None)
    args = parser.parse_args()
    kwargs = {}
    if args.run_id:
        kwargs["run_id"] = args.run_id
    if args.active_run_id:
        kwargs["active_run_id"] = args.active_run_id
    print(run_wag_activity_basis_audit(**kwargs)["summary"])
