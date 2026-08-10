from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fgo_bot.adb import AdbError, MuMuDevice
from fgo_bot.config import ensure_user_config, load_config


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "profiles" / "fgo_cn_1600x900.yaml"


class DistributionTests(unittest.TestCase):
    def test_shipped_config_has_no_machine_specific_mumu_path(self) -> None:
        config, _ = load_config(DEFAULT_CONFIG)
        self.assertIsNone(config["device"]["manager_path"])

    def test_user_config_is_copied_without_changing_default(self) -> None:
        original = DEFAULT_CONFIG.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            user_config = Path(directory) / "user.yaml"
            selected = ensure_user_config(DEFAULT_CONFIG, user_config)
            self.assertEqual(selected, user_config.resolve())
            self.assertEqual(user_config.read_bytes(), original)
            self.assertEqual(DEFAULT_CONFIG.read_bytes(), original)

    def test_mumu_lookup_is_lazy(self) -> None:
        with patch(
            "fgo_bot.adb.find_mumu_manager",
            side_effect=AdbError("not found"),
        ) as finder:
            device = MuMuDevice(None)
            finder.assert_not_called()
            with self.assertRaises(AdbError):
                device.info()


if __name__ == "__main__":
    unittest.main()
