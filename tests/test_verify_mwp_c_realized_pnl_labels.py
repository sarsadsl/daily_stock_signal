from __future__ import annotations

import unittest
from pathlib import Path


class RealizedPnlPageLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = Path("mwp_c_realized_pnl.html").read_text(encoding="utf-8")

    def test_page_contains_expected_user_facing_labels(self) -> None:
        expected_labels = [
            "MWP-C 已實現 / 未實現損益",
            "MWP-C 正式追蹤",
            "首頁總覽",
            "策略報告",
            "參數比較",
            "正式追蹤專屬摘要",
            "股票交易清單",
            "歷史交易",
            "正式追蹤",
            "個股 K 線圖",
            "清除搜尋",
            "放大",
            "縮小",
            "重設",
        ]

        for label in expected_labels:
            with self.subTest(label=label):
                self.assertIn(label, self.html)

    def test_trade_separator_does_not_render_as_question_mark(self) -> None:
        self.assertNotIn('class="trade-separator">?</span>', self.html)
        self.assertIn('class="trade-separator">·</span>', self.html)


if __name__ == "__main__":
    unittest.main()
