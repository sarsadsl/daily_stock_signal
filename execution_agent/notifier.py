from __future__ import annotations

from alert_signals import send_message
from execution_agent.open_entry_core import OpenEntryDecision


def render_open_entry_call_message(decision: OpenEntryDecision) -> str:
    stock_line = f"🏷️ {decision.stock_no} {decision.stock_name}".strip()
    return "\n".join(
        [
            "🚨 MWP-C 正式追蹤",
            stock_line,
            f"📅 訊號日 {decision.signal_date}",
            f"💵 收盤 {decision.signal_close}",
            f"🎯 進場上限 {decision.entry_limit_price}",
            f"🟢 次日開盤 {decision.open_price}",
        ]
    )


class TelegramNotifier:
    def send_open_entry_call(self, decision: OpenEntryDecision) -> bool:
        sent_channels = send_message(render_open_entry_call_message(decision), channels={"telegram"})
        return "telegram" in sent_channels
