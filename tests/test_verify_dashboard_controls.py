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

    def test_mwp_c_pages_use_button_navigation_in_topbar(self) -> None:
        for html in (self.strategy_html, self.realized_html):
            self.assertIn("data-nav-url=", html)
            self.assertNotIn('<a class="primary-button"', html)
            self.assertNotIn('<a class="mode-button"', html)


if __name__ == "__main__":
    unittest.main()
