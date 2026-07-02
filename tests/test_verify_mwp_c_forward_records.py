from __future__ import annotations

import unittest
from pathlib import Path

from verify_mwp_c_forward_records import verify_forward_records


class ForwardRecordVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracking = {
            "tracking": {
                "as_of_daily_signal_date": "2026-06-29",
                "daily_mwp_c_radar": {
                    "as_of_date": "2026-06-29",
                    "new_mother_candidates": [
                        {
                            "market": "TWSE",
                            "stock_no": "2330",
                            "signal_date": "2026-06-29",
                        }
                    ],
                    "addon_candidates": [
                        {
                            "market": "TPEX",
                            "stock_no": "6488",
                            "signal_date": "2026-06-29",
                            "mother_signal_date": "2026-05-20",
                            "addon_number": 1,
                        }
                    ],
                },
            }
        }
        self.records = [
            {"id": "TWSE:2330:2026-06-29:base"},
            {"id": "TPEX:6488:2026-05-20:addon:1"},
        ]

    def test_complete_cohort_passes(self) -> None:
        result = verify_forward_records("2026-06-29", self.tracking, self.records)

        self.assertEqual(result["expected_date"], "2026-06-29")
        self.assertEqual(result["candidate_records"], 2)
        self.assertEqual(result["forward_records"], 2)

    def test_missing_candidate_record_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing forward record IDs"):
            verify_forward_records("2026-06-29", self.tracking, self.records[:1])

    def test_duplicate_record_id_fails(self) -> None:
        duplicate_records = [*self.records, dict(self.records[0])]

        with self.assertRaisesRegex(ValueError, "Duplicate forward record IDs"):
            verify_forward_records("2026-06-29", self.tracking, duplicate_records)

    def test_tracking_date_mismatch_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tracking date mismatch"):
            verify_forward_records("2026-06-30", self.tracking, self.records)

    def test_daily_workflow_updates_verifies_and_commits_cohort(self) -> None:
        workflow = Path(".github/workflows/daily-signal.yml").read_text(
            encoding="utf-8"
        )

        freshness_index = workflow.index("- name: Verify report freshness")
        freshness_command_index = workflow.index(
            'python verify_daily_signal_freshness.py --expected-date "${{ inputs.as_of }}"'
        )
        tracker_index = workflow.index("python build_mwp_a_strategy_tracking.py")
        verifier_index = workflow.index("python verify_mwp_c_forward_records.py")
        site_index = workflow.index("- name: Build static site")

        self.assertLess(freshness_index, tracker_index)
        self.assertLess(freshness_index, freshness_command_index)
        self.assertLess(freshness_command_index, tracker_index)
        self.assertLess(tracker_index, verifier_index)
        self.assertLess(verifier_index, site_index)
        self.assertIn("reports/mwp_a_strategy_tracking.json", workflow)
        self.assertIn("reports/mwp_c_forward_records.json", workflow)

    def test_deploy_site_workflow_also_deploys_cloudflare_pages(self) -> None:
        workflow = Path(".github/workflows/deploy-site.yml").read_text(
            encoding="utf-8"
        )

        site_index = workflow.index("- name: Build static site")
        github_pages_index = workflow.index("- name: Deploy to GitHub Pages")

        self.assertIn("- name: Deploy to Cloudflare Pages", workflow)
        self.assertIn("uses: cloudflare/wrangler-action@v3", workflow)
        self.assertIn(
            "pages deploy site --project-name=daily-stock-signal --branch=main",
            workflow,
        )
        self.assertLess(site_index, github_pages_index)
        self.assertLess(
            github_pages_index, workflow.index("- name: Deploy to Cloudflare Pages")
        )


if __name__ == "__main__":
    unittest.main()
