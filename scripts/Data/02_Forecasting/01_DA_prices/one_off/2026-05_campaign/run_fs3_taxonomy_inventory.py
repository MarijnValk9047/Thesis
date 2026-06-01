from __future__ import annotations

import json
from pathlib import Path

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.external_features import fs3_taxonomy_inventory_frame, load_external_feature_store
from hourly_da.core.storage import write_csv


def main() -> None:
    config = HourlyDAPipelineConfig()
    store = load_external_feature_store(config)
    inventory = fs3_taxonomy_inventory_frame(config, store)

    docs_dir = Path(__file__).resolve().parent / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    csv_path = docs_dir / "fs3_taxonomy_inventory.csv"
    json_path = docs_dir / "fs3_taxonomy_inventory.json"

    write_csv(csv_path, inventory)
    json_path.write_text(json.dumps(inventory.to_dict(orient="records"), indent=2), encoding="utf-8")

    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    print(inventory[["family_group", "experiment_name", "currently_available", "availability_reason"]].to_string(index=False))


if __name__ == "__main__":
    main()
