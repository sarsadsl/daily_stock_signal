from __future__ import annotations

import unittest
from pathlib import Path


class DashboardControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.signal_html = Path("signal_dashboard.html").read_text(encoding="utf-8")
        self.strategy_html = Path("mwp_c_strategy.html").read_text(encoding="utf-8")
        self.realized_html = Path("mwp_c_realized_pnl.html").read_text(encoding="utf-8")

    def test_signal_dashboard_removes_requested_controls(self) -> None:
        for removed_id in ("searchInput", "marketFilter", "resetButton", "fileInput"):
            with self.subTest(removed_id=removed_id):
                self.assertNotIn(f'id="{removed_id}"', self.signal_html)

        self.assertIn('id="reasonFilter"', self.signal_html)

    def test_signal_dashboard_uses_button_navigation_for_topbar_reports(self) -> None:
        self.assertIn('data-nav-url="mwp_c_strategy.html"', self.signal_html)
        self.assertIn('data-nav-url="mwp_c_realized_pnl.html"', self.signal_html)
        self.assertIn(
            'data-nav-url="reports/pullback_experiment_summary.html"',
            self.signal_html,
        )
        self.assertNotIn(
            '<a class="mode-button report-link" href="mwp_c_strategy.html"',
            self.signal_html,
        )
        self.assertNotIn(
            '<a class="mode-button report-link" href="mwp_c_realized_pnl.html"',
            self.signal_html,
        )

    def test_signal_dashboard_toolbar_labels_are_readable(self) -> None:
        expected_labels = [
            'aria-label="工具列"',
            ">同步今日資料</button>",
            ">MWP-C追蹤</button>",
            ">MWP-C已/未損益</button>",
            ">Pullback總覽</button>",
            'aria-label="策略"',
            'aria-label="訊號"',
            ">夜間</button>",
            ">表格</button>",
            ">卡片</button>",
            'aria-label="重新讀取">↻</button>',
        ]

        for label in expected_labels:
            with self.subTest(label=label):
                self.assertIn(label, self.signal_html)

        forbidden_fragments = [
            'aria-label="???"',
            ">??????</button>",
            ">MWP-C??</button>",
            ">MWP-C?/???</button>",
            ">Pullback??</button>",
        ]

        for fragment in forbidden_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, self.signal_html)

    def test_mwp_c_pages_use_button_navigation_in_topbar(self) -> None:
        for html in (self.strategy_html, self.realized_html):
            self.assertIn("data-nav-url=", html)
            self.assertNotIn('<a class="primary-button"', html)
            self.assertNotIn('<a class="mode-button"', html)


if __name__ == "__main__":
    unittest.main()
