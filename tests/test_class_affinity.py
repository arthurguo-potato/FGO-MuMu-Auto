from __future__ import annotations

import unittest
from pathlib import Path

from fgo_bot.class_affinity import (
    ATTACK_ADVANTAGE,
    COUNTER_PRIORITY,
    counter_classes,
    has_attack_advantage,
)
from fgo_bot.config import load_config


class ClassAffinityTests(unittest.TestCase):
    def test_standard_and_extra_class_triangles(self) -> None:
        self.assertTrue(has_attack_advantage("saber", "lancer"))
        self.assertTrue(has_attack_advantage("lancer", "archer"))
        self.assertTrue(has_attack_advantage("archer", "saber"))
        self.assertTrue(has_attack_advantage("rider", "caster"))
        self.assertTrue(has_attack_advantage("caster", "assassin"))
        self.assertTrue(has_attack_advantage("assassin", "rider"))
        self.assertTrue(has_attack_advantage("ruler", "moon_cancer"))
        self.assertTrue(has_attack_advantage("moon_cancer", "avenger"))
        self.assertTrue(has_attack_advantage("avenger", "ruler"))
        self.assertTrue(has_attack_advantage("alter_ego", "foreigner"))
        self.assertTrue(has_attack_advantage("foreigner", "pretender"))
        self.assertTrue(has_attack_advantage("pretender", "alter_ego"))

    def test_berserker_foreigner_shielder_and_beast_exceptions(self) -> None:
        self.assertTrue(has_attack_advantage("berserker", "ruler"))
        self.assertFalse(has_attack_advantage("berserker", "foreigner"))
        self.assertFalse(has_attack_advantage("berserker", "shielder"))
        self.assertTrue(has_attack_advantage("foreigner", "berserker"))
        self.assertFalse(has_attack_advantage("beast", "saber"))
        self.assertTrue(has_attack_advantage("beast_draco", "saber"))
        self.assertTrue(
            has_attack_advantage(
                "beast_space_ereshkigal",
                "moon_cancer",
            )
        )
        self.assertTrue(has_attack_advantage("unbeast", "foreigner"))

    def test_support_counter_priority_uses_full_affinity_table(self) -> None:
        self.assertEqual(counter_classes("saber"), ["archer"])
        self.assertEqual(counter_classes("alter_ego"), ["pretender"])
        self.assertEqual(counter_classes("pretender"), ["foreigner"])
        self.assertEqual(counter_classes("foreigner"), ["alter_ego"])
        self.assertEqual(counter_classes("shielder"), [])
        self.assertEqual(counter_classes("beast"), [])
        self.assertEqual(
            counter_classes("beast_space_ereshkigal"),
            ["avenger"],
        )

    def test_profile_affinity_overrides_match_built_in_official_table(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config, _ = load_config(
            project_root / "profiles" / "fgo_cn_1600x900.yaml"
        )
        battle_map = config["battle"]["class_advantage_map"]
        support_map = config["support"]["counter_map"]
        self.assertEqual(set(battle_map), set(ATTACK_ADVANTAGE))
        self.assertEqual(set(support_map), set(COUNTER_PRIORITY))
        for class_name, targets in ATTACK_ADVANTAGE.items():
            self.assertEqual(set(battle_map[class_name]), set(targets))
        for class_name, counters in COUNTER_PRIORITY.items():
            self.assertEqual(
                list(support_map[class_name]),
                list(counters),
            )


if __name__ == "__main__":
    unittest.main()
