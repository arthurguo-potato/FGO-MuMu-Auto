from __future__ import annotations

import unittest
from pathlib import Path

from fgo_bot.config import load_config
from fgo_bot.gui import (
    BATTLE_RULE_DEFAULTS,
    BATTLE_RULE_GROUPS,
    SUPPORT_RULE_DEFAULTS,
    SUPPORT_RULE_GROUPS,
)


class BattleRuleGuiTests(unittest.TestCase):
    def test_profile_contains_every_visible_rule_with_declared_default(self) -> None:
        keys = [
            key
            for _group_name, options in BATTLE_RULE_GROUPS
            for key, _label, _description in options
        ]
        self.assertEqual(len(keys), len(set(keys)))

        project_root = Path(__file__).resolve().parents[1]
        config, _ = load_config(
            project_root / "profiles" / "fgo_cn_1600x900.yaml"
        )
        configured = config["battle"]["rule_options"]
        self.assertEqual(set(keys), set(configured))
        expected = {
            key: BATTLE_RULE_DEFAULTS.get(key, True)
            for key in keys
        }
        self.assertEqual(configured, expected)
        self.assertFalse(configured["prefer_arts_chain"])

    def test_profile_contains_every_support_rule_with_visible_default(self) -> None:
        keys = [
            key
            for _group_name, options in SUPPORT_RULE_GROUPS
            for key, _label, _description in options
        ]
        self.assertEqual(keys[0], "use_forced_support")
        self.assertEqual(len(keys), len(set(keys)))

        project_root = Path(__file__).resolve().parents[1]
        config, _ = load_config(
            project_root / "profiles" / "fgo_cn_1600x900.yaml"
        )
        configured = config["support"]["strategy_options"]
        self.assertEqual(set(keys), set(configured))
        expected = {
            key: SUPPORT_RULE_DEFAULTS.get(key, True)
            for key in keys
        }
        self.assertEqual(configured, expected)
        self.assertTrue(configured["prefer_aoe_np"])
        self.assertFalse(configured["require_aoe_np"])


if __name__ == "__main__":
    unittest.main()
