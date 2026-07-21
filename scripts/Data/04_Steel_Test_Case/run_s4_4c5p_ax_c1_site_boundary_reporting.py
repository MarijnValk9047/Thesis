import argparse

from steel.s4_4c5p_ax_c1_site_boundary_reporting import run_c1_site_boundary_reporting


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile C1 site-boundary reporting from one physical run.")
    parser.add_argument("--config", default=None, help="Optional site-boundary-reporting YAML.")
    args = parser.parse_args()
    result = run_c1_site_boundary_reporting(**({"config_path": args.config} if args.config else {}))
    print(result["run_directory"])
