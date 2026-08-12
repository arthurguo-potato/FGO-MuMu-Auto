from __future__ import annotations

import unittest

import numpy as np

from fgo_bot.runner import BotRunner


class FirstSupportSelectionTests(unittest.TestCase):
    def test_first_mode_taps_first_row_without_recognition(self) -> None:
        runner = BotRunner.__new__(BotRunner)
        runner.config = {
            "screen": {"base_width": 1600, "base_height": 900},
            "support": {
                "strategy_options": {"selection_mode": "first"},
                "first_support_click_point": [750, 350],
            },
        }
        runner.selected_support = object()
        runner.support_refreshes = 2
        runner.support_selector = None
        logs: list[str] = []
        taps: list[tuple[tuple[int, int], str]] = []
        runner.log = logs.append
        runner._reset_support_class_search = lambda: None
        runner._tap = lambda point, label: taps.append((point, label))

        screen = np.zeros((900, 1600, 3), dtype=np.uint8)
        runner._select_support_action(screen, object())

        self.assertIsNone(runner.selected_support)
        self.assertEqual(runner.support_refreshes, 0)
        self.assertEqual(taps, [((750, 350), "列表第一位助战")])
        self.assertIn("包括客将", logs[0])


if __name__ == "__main__":
    unittest.main()
