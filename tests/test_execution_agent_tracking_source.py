import unittest

from execution_agent.tracking_source import load_tracking_payload_from_text, select_pending_open_entries


class TrackingSourceTests(unittest.TestCase):
    def test_load_tracking_payload_from_text_decodes_json(self) -> None:
        payload = load_tracking_payload_from_text('{"tracking": {"formal_forward_records": []}}')

        self.assertEqual(payload["tracking"]["formal_forward_records"], [])

    def test_select_pending_open_entries_keeps_only_pending_records(self) -> None:
        payload = {
            "tracking": {
                "formal_forward_records": [
                    {
                        "market": "TWSE",
                        "stock_no": "3094",
                        "stock_name": "xx",
                        "signal_date": "2026-07-08",
                        "status": "待次日開盤",
                        "entry_limit_price": 41.65,
                        "signal_close": 42.5,
                        "unit_type": "base",
                        "addon_number": None,
                    },
                    {
                        "market": "TWSE",
                        "stock_no": "3090",
                        "stock_name": "yy",
                        "signal_date": "2026-07-08",
                        "status": "持有中",
                        "entry_limit_price": 297.43,
                        "signal_close": 303.5,
                        "unit_type": "base",
                        "addon_number": None,
                    },
                ]
            }
        }

        rows = select_pending_open_entries(payload, signal_date="2026-07-08")

        self.assertEqual([row.stock_no for row in rows], ["3094"])
        self.assertEqual(rows[0].entry_limit_price, 41.65)
