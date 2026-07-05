from __future__ import annotations

import unittest
from unittest.mock import patch

from send_telegram_test_message import build_test_message, send_test_message


class TelegramTestMessageTests(unittest.TestCase):
    def test_build_test_message_matches_expected_format(self) -> None:
        message = build_test_message()

        self.assertEqual(
            message,
            "\n".join(
                [
                    "[測試訊息]",
                    "MWP-C 正式追蹤開盤進場提醒",
                    "TWSE 2330 台積電",
                    "訊號日 2026-07-03",
                    "D0 收盤 1000.0",
                    "進場上限 980.0",
                    "次日開盤 975.0",
                    "符合正式追蹤次日開盤進場條件。",
                ]
            ),
        )

    @patch("send_telegram_test_message.send_message")
    def test_send_test_message_requires_telegram_success(self, mock_send_message) -> None:
        mock_send_message.return_value = ["telegram"]

        send_test_message()

        mock_send_message.assert_called_once_with(build_test_message(), channels={"telegram"})

    @patch("send_telegram_test_message.send_message")
    def test_send_test_message_raises_when_telegram_not_sent(self, mock_send_message) -> None:
        mock_send_message.return_value = []

        with self.assertRaisesRegex(RuntimeError, "Telegram test message was not sent"):
            send_test_message()


if __name__ == "__main__":
    unittest.main()
