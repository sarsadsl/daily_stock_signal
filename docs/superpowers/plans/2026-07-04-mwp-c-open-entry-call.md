# MWP-C Open Entry Call Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone MWP-C formal-tracking open-entry call script that sends one Telegram alert when the next trading day's official open satisfies the existing `D0 close * 0.98` entry rule.

**Architecture:** Keep the feature isolated from the static-site UI and the existing formal-tracking batch updater. Implement a standalone script that reads `reports/mwp_a_strategy_tracking.json`, filters `待次日開盤` records, fetches `D1` official daily open values from the existing market endpoints, compares them against `entry_limit_price`, and writes a small dedupe/audit log before sending through the current Telegram transport.

**Tech Stack:** Python 3, existing project JSON files, existing market daily fetch helpers from `dashboard_server.py`, existing Telegram send helper from `alert_signals.py`, `unittest`.

## Global Constraints

- Do not change the current formal-tracking entry rule.
- Do not introduce intraday low-based or 1-minute-K-based entries.
- Do not rename `reports/mwp_a_strategy_tracking.json` in this version.
- Do not create a new Telegram channel.
- Do not rewrite the `formal_forward_records` generation semantics.
- Trigger only on `D1` official open, not later intraday lows.
- Use `entry_limit_price` as the official threshold, aligned with existing formal tracking.

---

### Task 1: Build Candidate Selection And Sent-Log Keys

**Files:**
- Create: `send_mwp_c_open_entry_calls.py`
- Create: `tests/test_mwp_c_open_entry_calls.py`

**Interfaces:**
- Consumes: `reports/mwp_a_strategy_tracking.json` payload structure, especially `tracking.formal_forward_records`
- Produces:
  - `load_tracking_payload(path: Path) -> dict[str, Any]`
  - `record_call_key(record: dict[str, Any]) -> str`
  - `select_pending_open_call_candidates(records: list[dict[str, Any]], as_of_date: str, sent_log: dict[str, Any]) -> list[dict[str, Any]]`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import unittest

from send_mwp_c_open_entry_calls import (
    record_call_key,
    select_pending_open_call_candidates,
)


class OpenEntryCallSelectionTests(unittest.TestCase):
    def test_selects_only_pending_next_open_records_for_d1(self) -> None:
        records = [
            {
                "market": "TWSE",
                "stock_no": "2330",
                "stock_name": "台積電",
                "signal_date": "2026-07-03",
                "status": "待次日開盤",
                "entry_limit_price": 980.0,
                "unit_type": "base",
            },
            {
                "market": "TWSE",
                "stock_no": "2317",
                "stock_name": "鴻海",
                "signal_date": "2026-07-03",
                "status": "持有中",
                "entry_limit_price": 180.0,
                "unit_type": "base",
            },
            {
                "market": "TPEX",
                "stock_no": "6488",
                "stock_name": "環球晶",
                "signal_date": "2026-07-02",
                "status": "待次日開盤",
                "entry_limit_price": 420.0,
                "unit_type": "base",
            },
        ]

        sent_log = {
            "calls": [
                {"key": "TWSE:2330:2026-07-03:base:-", "result": "called"}
            ]
        }

        selected = select_pending_open_call_candidates(
            records,
            as_of_date="2026-07-04",
            sent_log=sent_log,
        )

        self.assertEqual([record["stock_no"] for record in selected], ["6488"])

    def test_record_call_key_includes_unit_identity(self) -> None:
        key = record_call_key(
            {
                "market": "TWSE",
                "stock_no": "2330",
                "signal_date": "2026-07-03",
                "unit_type": "addon",
                "addon_number": 2,
            }
        )

        self.assertEqual(key, "TWSE:2330:2026-07-03:addon:2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_mwp_c_open_entry_calls.OpenEntryCallSelectionTests -v`

Expected: FAIL with `ModuleNotFoundError` or missing function import errors for `send_mwp_c_open_entry_calls`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


TRACKING_PATH = Path("reports/mwp_a_strategy_tracking.json")
CALL_LOG_PATH = Path("reports/mwp_c_open_entry_calls.json")


def load_tracking_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def record_call_key(record: dict[str, Any]) -> str:
    market = str(record.get("market") or "").upper()
    stock_no = str(record.get("stock_no") or "")
    signal_date = str(record.get("signal_date") or "")
    unit_type = str(record.get("unit_type") or "base")
    addon_number = record.get("addon_number")
    addon_part = "-" if addon_number in {None, ""} else str(addon_number)
    return f"{market}:{stock_no}:{signal_date}:{unit_type}:{addon_part}"


def _next_calendar_date(signal_date: str) -> str:
    return (date.fromisoformat(signal_date) + timedelta(days=1)).isoformat()


def select_pending_open_call_candidates(
    records: list[dict[str, Any]],
    as_of_date: str,
    sent_log: dict[str, Any],
) -> list[dict[str, Any]]:
    sent_keys = {
        str(item.get("key"))
        for item in sent_log.get("calls", [])
        if item.get("key")
    }
    selected: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("status") or "") != "待次日開盤":
            continue
        if not record.get("entry_limit_price"):
            continue
        if _next_calendar_date(str(record.get("signal_date") or "")) != as_of_date:
            continue
        key = record_call_key(record)
        if key in sent_keys:
            continue
        selected.append(record)
    return selected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_mwp_c_open_entry_calls.OpenEntryCallSelectionTests -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add send_mwp_c_open_entry_calls.py tests/test_mwp_c_open_entry_calls.py
git commit -m "Add MWP-C open-entry call candidate selection"
```

### Task 2: Add Official Open Fetch And Trigger Decisions

**Files:**
- Modify: `send_mwp_c_open_entry_calls.py`
- Modify: `tests/test_mwp_c_open_entry_calls.py`

**Interfaces:**
- Consumes:
  - `record_call_key(record: dict[str, Any]) -> str`
  - `select_pending_open_call_candidates(records: list[dict[str, Any]], as_of_date: str, sent_log: dict[str, Any]) -> list[dict[str, Any]]`
  - `dashboard_server.fetch_daily_rows(market: str, target_date: date) -> dict[str, dict[str, Any]]`
- Produces:
  - `fetch_market_open_snapshot(markets: list[str], target_date: date) -> dict[tuple[str, str], float]`
  - `build_open_entry_call_decisions(records: list[dict[str, Any]], open_snapshot: dict[tuple[str, str], float]) -> list[dict[str, Any]]`
  - `render_open_entry_call_message(decision: dict[str, Any]) -> str`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import unittest

from send_mwp_c_open_entry_calls import (
    build_open_entry_call_decisions,
    render_open_entry_call_message,
)


class OpenEntryCallDecisionTests(unittest.TestCase):
    def test_builds_called_and_open_failed_results_from_official_open(self) -> None:
        records = [
            {
                "market": "TWSE",
                "stock_no": "2330",
                "stock_name": "台積電",
                "signal_date": "2026-07-03",
                "entry_limit_price": 980.0,
                "unit_type": "base",
                "signal_close": 1000.0,
            },
            {
                "market": "TWSE",
                "stock_no": "2317",
                "stock_name": "鴻海",
                "signal_date": "2026-07-03",
                "entry_limit_price": 180.0,
                "unit_type": "base",
                "signal_close": 183.0,
            },
        ]

        open_snapshot = {
            ("TWSE", "2330"): 975.0,
            ("TWSE", "2317"): 181.0,
        }

        decisions = build_open_entry_call_decisions(records, open_snapshot)

        self.assertEqual([item["result"] for item in decisions], ["called", "open_failed"])
        self.assertEqual(decisions[0]["open_price"], 975.0)
        self.assertEqual(decisions[1]["open_price"], 181.0)

    def test_render_message_contains_threshold_and_official_open(self) -> None:
        message = render_open_entry_call_message(
            {
                "market": "TWSE",
                "stock_no": "2330",
                "stock_name": "台積電",
                "signal_date": "2026-07-03",
                "signal_close": 1000.0,
                "entry_limit_price": 980.0,
                "open_price": 975.0,
            }
        )

        self.assertIn("MWP-C 正式追蹤開盤進場", message)
        self.assertIn("2330 台積電", message)
        self.assertIn("Signal date 2026-07-03", message)
        self.assertIn("Entry limit 980.0", message)
        self.assertIn("D1 open 975.0", message)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_mwp_c_open_entry_calls.OpenEntryCallDecisionTests -v`

Expected: FAIL with missing function import errors.

- [ ] **Step 3: Write minimal implementation**

```python
from datetime import date

from dashboard_server import fetch_daily_rows


def fetch_market_open_snapshot(markets: list[str], target_date: date) -> dict[tuple[str, str], float]:
    snapshot: dict[tuple[str, str], float] = {}
    for market in markets:
        rows = fetch_daily_rows(market, target_date)
        for code, item in rows.items():
            open_text = str(item.get("open") or "").strip()
            if not open_text:
                continue
            snapshot[(market.upper(), code)] = float(open_text)
    return snapshot


def build_open_entry_call_decisions(
    records: list[dict[str, Any]],
    open_snapshot: dict[tuple[str, str], float],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for record in records:
        key = (str(record.get("market") or "").upper(), str(record.get("stock_no") or ""))
        open_price = open_snapshot.get(key)
        if open_price is None:
            continue
        entry_limit_price = float(record.get("entry_limit_price") or 0)
        result = "called" if open_price <= entry_limit_price else "open_failed"
        decisions.append(
            {
                **record,
                "key": record_call_key(record),
                "open_price": open_price,
                "result": result,
            }
        )
    return decisions


def render_open_entry_call_message(decision: dict[str, Any]) -> str:
    return "\n".join(
        [
            "MWP-C 正式追蹤開盤進場",
            f"{decision['market']} {decision['stock_no']} {decision['stock_name']}",
            f"Signal date {decision['signal_date']}",
            f"D0 close {decision.get('signal_close', '-')}",
            f"Entry limit {decision['entry_limit_price']}",
            f"D1 open {decision['open_price']}",
            "已符合正式追蹤進場條件",
        ]
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_mwp_c_open_entry_calls.OpenEntryCallDecisionTests -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add send_mwp_c_open_entry_calls.py tests/test_mwp_c_open_entry_calls.py
git commit -m "Add MWP-C open-entry call decisions"
```

### Task 3: Wire CLI, Dry-Run, Telegram Send, And Log Persistence

**Files:**
- Modify: `send_mwp_c_open_entry_calls.py`
- Modify: `tests/test_mwp_c_open_entry_calls.py`
- Modify: `CODEX_HANDOFF.md`

**Interfaces:**
- Consumes:
  - `load_tracking_payload(path: Path) -> dict[str, Any]`
  - `select_pending_open_call_candidates(records: list[dict[str, Any]], as_of_date: str, sent_log: dict[str, Any]) -> list[dict[str, Any]]`
  - `fetch_market_open_snapshot(markets: list[str], target_date: date) -> dict[tuple[str, str], float]`
  - `build_open_entry_call_decisions(records: list[dict[str, Any]], open_snapshot: dict[tuple[str, str], float]) -> list[dict[str, Any]]`
  - `render_open_entry_call_message(decision: dict[str, Any]) -> str`
  - `alert_signals.send_message(message: str, channels: set[str] | None = None, image_urls: list[str] | None = None, image_paths: list[Path] | None = None) -> list[str]`
- Produces:
  - `load_call_log(path: Path) -> dict[str, Any]`
  - `write_call_log(path: Path, payload: dict[str, Any]) -> None`
  - `run_open_entry_calls(as_of_date: date, dry_run: bool, markets: list[str]) -> list[dict[str, Any]]`
  - CLI entrypoint for `python send_mwp_c_open_entry_calls.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from send_mwp_c_open_entry_calls import load_call_log, run_open_entry_calls, write_call_log


class OpenEntryCallCliTests(unittest.TestCase):
    def test_call_log_round_trip_uses_calls_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calls.json"
            write_call_log(path, {"calls": [{"key": "TWSE:2330:2026-07-03:base:-", "result": "called"}]})
            payload = load_call_log(path)
        self.assertEqual(payload["calls"][0]["key"], "TWSE:2330:2026-07-03:base:-")

    @patch("send_mwp_c_open_entry_calls.send_message")
    @patch("send_mwp_c_open_entry_calls.fetch_market_open_snapshot")
    @patch("send_mwp_c_open_entry_calls.load_tracking_payload")
    def test_dry_run_does_not_send_telegram_or_write_called_result(
        self,
        mock_load_tracking_payload,
        mock_fetch_market_open_snapshot,
        mock_send_message,
    ) -> None:
        mock_load_tracking_payload.return_value = {
            "tracking": {
                "formal_forward_records": [
                    {
                        "market": "TWSE",
                        "stock_no": "2330",
                        "stock_name": "台積電",
                        "signal_date": "2026-07-03",
                        "status": "待次日開盤",
                        "entry_limit_price": 980.0,
                        "signal_close": 1000.0,
                        "unit_type": "base",
                    }
                ]
            }
        }
        mock_fetch_market_open_snapshot.return_value = {("TWSE", "2330"): 975.0}

        decisions = run_open_entry_calls(
            as_of_date=date.fromisoformat("2026-07-04"),
            dry_run=True,
            markets=["twse"],
        )

        self.assertEqual(decisions[0]["result"], "called")
        mock_send_message.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_mwp_c_open_entry_calls.OpenEntryCallCliTests -v`

Expected: FAIL with missing function import errors or missing mock targets.

- [ ] **Step 3: Write minimal implementation**

```python
import argparse
from datetime import date

from alert_signals import send_message


def load_call_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"calls": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_call_log(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_open_entry_calls(as_of_date: date, dry_run: bool, markets: list[str]) -> list[dict[str, Any]]:
    payload = load_tracking_payload(TRACKING_PATH)
    sent_log = load_call_log(CALL_LOG_PATH)
    records = payload.get("tracking", {}).get("formal_forward_records", [])
    selected = select_pending_open_call_candidates(records, as_of_date.isoformat(), sent_log)
    open_snapshot = fetch_market_open_snapshot(markets, as_of_date)
    decisions = build_open_entry_call_decisions(selected, open_snapshot)

    if dry_run:
        for decision in decisions:
            print(f"[DRY-RUN] {decision['key']} {decision['result']} open={decision['open_price']}")
        return decisions

    calls = sent_log.setdefault("calls", [])
    for decision in decisions:
        calls.append(
            {
                "key": decision["key"],
                "market": decision["market"],
                "stock_no": decision["stock_no"],
                "signal_date": decision["signal_date"],
                "unit_type": decision.get("unit_type"),
                "addon_number": decision.get("addon_number"),
                "checked_date": as_of_date.isoformat(),
                "open_price": decision["open_price"],
                "entry_limit_price": decision["entry_limit_price"],
                "result": decision["result"],
            }
        )
        if decision["result"] == "called":
            sent = send_message(render_open_entry_call_message(decision), channels={"telegram"})
            if "telegram" in sent:
                calls[-1]["sent_at"] = as_of_date.isoformat()
    write_call_log(CALL_LOG_PATH, sent_log)
    return decisions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send MWP-C formal-tracking open entry calls.")
    parser.add_argument("--as-of", required=True, help="Market date in YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true", help="Print decisions without sending Telegram or writing final send state.")
    parser.add_argument("--market", default="twse,tpex", help="Comma-separated markets.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    markets = [item.strip().casefold() for item in args.market.split(",") if item.strip()]
    run_open_entry_calls(date.fromisoformat(args.as_of), args.dry_run, markets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_mwp_c_open_entry_calls.OpenEntryCallCliTests -v`

Expected: PASS

- [ ] **Step 5: Run full verification**

Run: `python -m unittest tests.test_mwp_c_open_entry_calls -v`
Expected: PASS

Run: `python -m unittest discover -s tests -v`
Expected: PASS

Run: `python send_mwp_c_open_entry_calls.py --as-of 2026-07-04 --dry-run`
Expected: prints zero or more deterministic call decisions, without Telegram send

- [ ] **Step 6: Update handoff**

Record the script path, sent-log path, verification commands, and the first dry-run usage example in `CODEX_HANDOFF.md`.

- [ ] **Step 7: Commit**

```bash
git add send_mwp_c_open_entry_calls.py tests/test_mwp_c_open_entry_calls.py CODEX_HANDOFF.md
git commit -m "Add MWP-C open-entry Telegram calls"
```

## Self-Review

- Spec coverage:
  - standalone script: Task 1-3
  - formal-forward candidate filtering: Task 1
  - `D1` official open check: Task 2
  - Telegram reuse: Task 3
  - sent-log and dedupe: Task 3
  - dry-run mode: Task 3
  - no intraday low logic: enforced by Task 2 interface and tests
- Placeholder scan:
  - no `TODO` / `TBD`
  - each task includes exact file paths, code, commands, and expected results
- Type consistency:
  - `record_call_key`, `select_pending_open_call_candidates`, `fetch_market_open_snapshot`, `build_open_entry_call_decisions`, and `run_open_entry_calls` are defined once and reused consistently across later tasks
