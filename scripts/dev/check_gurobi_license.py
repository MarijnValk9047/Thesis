from __future__ import annotations

import argparse
import os
from pathlib import Path

import gurobipy as gp
from gurobipy import GRB


LICENSE_ENV_VARS = (
    "GRB_LICENSE_FILE",
    "GUROBI_LICENSE_FILE",
    "THESIS_GUROBI_LICENSE_PATH",
)


def _apply_license_path(path: Path | None) -> None:
    if path is None:
        return
    if not path.exists():
        raise FileNotFoundError(f"Gurobi license file not found: {path}")
    os.environ["GRB_LICENSE_FILE"] = str(path)


def _resolve_license_path(cli_path: Path | None) -> Path | None:
    if cli_path is not None:
        return cli_path
    for env_name in LICENSE_ENV_VARS:
        raw = os.environ.get(env_name)
        if raw:
            return Path(raw)
    return None


def run_large_license_check(n: int = 3000) -> tuple[int, float]:
    model = gp.Model("license_size_check")
    x = model.addVars(range(n), lb=0.0, name="x")
    for i in range(n):
        model.addConstr(x[i] <= 1.0, name=f"ub_{i}")
    model.setObjective(gp.quicksum(x[i] for i in range(n)), GRB.MAXIMIZE)
    model.optimize()
    return int(model.Status), float(model.ObjVal if model.SolCount > 0 else float("nan"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Check that full Gurobi license is used (non-restricted).")
    parser.add_argument("--license-path", type=Path, default=None)
    parser.add_argument("--vars", type=int, default=3000)
    args = parser.parse_args()

    _apply_license_path(_resolve_license_path(args.license_path))
    status, objective = run_large_license_check(n=int(args.vars))
    succeeded = status == GRB.OPTIMAL and abs(objective - float(args.vars)) <= 1e-6

    print(f"status={status}")
    print(f"objective={objective:.6f}")
    print(f"success={succeeded}")


if __name__ == "__main__":
    main()
