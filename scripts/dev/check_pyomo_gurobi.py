from __future__ import annotations

import argparse
import os
from pathlib import Path

import pyomo.environ as pyo


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Check that Pyomo can solve with Gurobi.")
    parser.add_argument("--license-path", type=Path, default=None)
    args = parser.parse_args()

    _apply_license_path(_resolve_license_path(args.license_path))

    model = pyo.ConcreteModel()
    model.x = pyo.Var(domain=pyo.NonNegativeReals)
    model.y = pyo.Var(domain=pyo.NonNegativeReals)
    model.obj = pyo.Objective(expr=2.0 * model.x + model.y, sense=pyo.maximize)
    model.c1 = pyo.Constraint(expr=model.x + model.y <= 10.0)
    model.c2 = pyo.Constraint(expr=model.x <= 4.0)

    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(False):
        raise RuntimeError("Pyomo SolverFactory('gurobi') is unavailable in this environment.")
    result = solver.solve(model, tee=False)

    status = getattr(result.solver, "status", None)
    termination = getattr(result.solver, "termination_condition", None)
    objective = pyo.value(model.obj)
    print(f"solver_status={status}")
    print(f"termination_condition={termination}")
    print(f"objective={objective:.6f}")


if __name__ == "__main__":
    main()
