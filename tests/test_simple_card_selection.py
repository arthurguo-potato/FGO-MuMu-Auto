from __future__ import annotations

import unittest

import numpy as np

from fgo_bot.runner import BotRunner


class SimpleCardSelectionTests(unittest.TestCase):
    def test_taps_first_three_cards_in_order_without_analysis(self) -> None:
        runner = BotRunner.__new__(BotRunner)
        runner.config = {
            "screen": {"base_width": 1600, "base_height": 900},
            "battle": {
                "default_cards": ["card1", "card2", "card3"],
                "card_points": {
                    "card1": [170, 675],
                    "card2": [485, 675],
                    "card3": [800, 675],
                },
                "between_cards_seconds": 0,
            },
        }
        runner._pending_np_slots = {1, 2}
        runner.log = lambda message: None
        runner._wait_interruptibly = lambda seconds: None
        taps: list[tuple[tuple[int, int], str]] = []
        runner._tap = lambda point, label: taps.append((point, label))

        runner._tap_first_three_cards(
            np.zeros((900, 1600, 3), dtype=np.uint8)
        )

        self.assertEqual(
            taps,
            [
                ((170, 675), "指令卡 card1"),
                ((485, 675), "指令卡 card2"),
                ((800, 675), "指令卡 card3"),
            ],
        )
        self.assertEqual(runner._pending_np_slots, set())


if __name__ == "__main__":
    unittest.main()
