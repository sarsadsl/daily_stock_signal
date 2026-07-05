#!/usr/bin/env python3
"""Send a one-off Telegram test message for the MWP-C open-entry alert."""

from __future__ import annotations

from alert_signals import send_message


def build_test_message() -> str:
    return "\n".join(
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
    )


def send_test_message() -> None:
    sent = send_message(build_test_message(), channels={"telegram"})
    if "telegram" not in sent:
        raise RuntimeError("Telegram test message was not sent")


def main() -> int:
    send_test_message()
    print("Telegram test message sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
