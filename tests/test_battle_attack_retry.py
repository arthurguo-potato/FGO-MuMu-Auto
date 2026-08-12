from __future__ import annotations

import unittest

import numpy as np

from fgo_bot.runner import BotRunner


class _Matcher:
    def __init__(self) -> None:
        self.rule = None

    def match_rule(self, screen, rule):
        self.rule = rule
        return object()


class BattleAttackRetryTests(unittest.TestCase):
    def test_battle_attack_is_always_repeatable(self) -> None:
        self.assertTrue(
            BotRunner._rule_allows_repeat(
                {"name": "battle_attack"},
                "battle",
            )
        )

    def test_other_rules_still_require_explicit_repeat(self) -> None:
        self.assertFalse(
            BotRunner._rule_allows_repeat(
                {"name": "party_start"},
                "tap_match",
            )
        )

    def test_retry_uses_relaxed_configured_threshold(self) -> None:
        runner = BotRunner.__new__(BotRunner)
        runner.config = {
            "battle": {"attack_retry_match_threshold": 0.65},
        }
        runner.matcher = _Matcher()

        result = runner._battle_attack_retry_match(
            np.zeros((10, 10, 3), dtype=np.uint8),
            {"name": "battle_attack", "threshold": 0.86},
        )

        self.assertIsNotNone(result)
        self.assertEqual(runner.matcher.rule["threshold"], 0.65)

    def test_retry_never_raises_original_threshold(self) -> None:
        runner = BotRunner.__new__(BotRunner)
        runner.config = {
            "battle": {"attack_retry_match_threshold": 0.9},
        }
        runner.matcher = _Matcher()

        runner._battle_attack_retry_match(
            np.zeros((10, 10, 3), dtype=np.uint8),
            {"name": "battle_attack", "threshold": 0.86},
        )

        self.assertEqual(runner.matcher.rule["threshold"], 0.86)


if __name__ == "__main__":
    unittest.main()
