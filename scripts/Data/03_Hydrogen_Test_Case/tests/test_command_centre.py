from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.command_centre import (  # noqa: E402
    command_centre_output_mode_to_policy,
    load_command_centre_config,
    load_supported_options,
    validate_command_centre_config,
)


ROOT = Path(__file__).resolve().parents[4]
COMMAND_CENTRE_CONFIG = ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "optimisation_command_centre.yaml"
SUPPORTED_OPTIONS = ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "optimisation_supported_options.yaml"


class CommandCentreValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.supported_options = load_supported_options(SUPPORTED_OPTIONS)
        self.payload = load_command_centre_config(COMMAND_CENTRE_CONFIG)

    def test_default_command_centre_config_validates(self) -> None:
        resolved = validate_command_centre_config(self.payload, supported_options=self.supported_options)
        self.assertEqual(resolved["backend"], "selected_week_hydrogen_fastpath_v1")
        self.assertEqual(resolved["scope"]["split"], "validation")
        self.assertEqual(resolved["scope"]["selected_regimes"], ["high_price"])

    def test_quarter_hour_is_refused_as_planned_option(self) -> None:
        payload = dict(self.payload)
        payload["granularity"] = "quarter_hour"
        with self.assertRaisesRegex(ValueError, "planned but not implemented"):
            validate_command_centre_config(payload, supported_options=self.supported_options)

    def test_test_split_tuning_run_is_refused(self) -> None:
        payload = dict(self.payload)
        payload["split"] = "test"
        payload["run_purpose"] = "validation tuning"
        with self.assertRaisesRegex(ValueError, "Test split is forbidden"):
            validate_command_centre_config(payload, supported_options=self.supported_options)

    def test_output_mode_mapping(self) -> None:
        self.assertEqual(command_centre_output_mode_to_policy("speed"), "minimal")
        self.assertEqual(command_centre_output_mode_to_policy("minimal"), "minimal")
        self.assertEqual(command_centre_output_mode_to_policy("audit"), "audit")
        self.assertEqual(command_centre_output_mode_to_policy("full"), "full")

    def test_deprecated_selected_weeks_path_is_refused(self) -> None:
        payload = dict(self.payload)
        payload["selected_week_config_validation"] = "scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks.yaml"
        with self.assertRaisesRegex(ValueError, "Deprecated selected_weeks.yaml"):
            validate_command_centre_config(payload, supported_options=self.supported_options)

    def test_doctor_style_temp_config_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir) / "command_centre.yaml"
            temp_path.write_text(yaml.safe_dump(self.payload, sort_keys=False), encoding="utf-8")
            payload = load_command_centre_config(temp_path)
            resolved = validate_command_centre_config(payload, supported_options=self.supported_options)
            self.assertEqual(resolved["general"]["method_version"], "optimisation_command_centre_v1")


if __name__ == "__main__":
    unittest.main()
