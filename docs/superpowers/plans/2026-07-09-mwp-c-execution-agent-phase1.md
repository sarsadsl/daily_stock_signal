# MWP-C Execution Agent Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可部署到 GCP VM 的第一階段 execution agent，準時讀取正式追蹤 `待次日開盤` 名單，依正式追蹤原規則判斷是否符合開盤進場，並發送 Telegram call 訊與寫入可稽核狀態。

**Architecture:** 第一階段不碰下單，先把「正式追蹤買進 call」從 GitHub Actions 排程拆成一個可在 VM 常駐或定時啟動的 Python agent。Agent 會重用現有 repo 的正式追蹤資料與 Telegram 發送能力，但把資料同步、候選篩選、開盤判斷、去重紀錄與 CLI 執行流程拆成清楚模組，方便第二階段再接永豐沙盒單。

**Tech Stack:** Python 3.12、`unittest`、`sqlite3`、`urllib.request`、現有 `alert_signals.py` Telegram 發送函式、GCP Compute Engine、Docker Compose

## Global Constraints

- 正式追蹤來源固定為 `reports/mwp_a_strategy_tracking.json` 的 `tracking.formal_forward_records`
- 不改動 `build_mwp_a_strategy_tracking.py` 的正式追蹤判斷語意
- 不改動網站頁面或 nightly GitHub 報表部署流程
- 第一階段只做 Telegram 開盤 call，不做 sandbox/live order
- 開盤判斷規則必須與現有 `send_mwp_c_open_entry_calls.py` 對齊：`open_price <= entry_limit_price`
- Agent 狀態第一階段使用 SQLite 儲存
- 部署目標固定為 GCP Compute Engine `asia-east1`

---

## File Structure

- Create: `execution_agent/__init__.py`
  - Agent package marker
- Create: `execution_agent/config.py`
  - 集中讀取環境變數與執行設定
- Create: `execution_agent/tracking_source.py`
  - 載入 tracking JSON、挑出當日 `待次日開盤` 記錄、轉成 typed records
- Create: `execution_agent/open_entry_core.py`
  - 開盤價比對與 decision 產生
- Create: `execution_agent/state_store.py`
  - SQLite call log、去重、稽核寫入
- Create: `execution_agent/notifier.py`
  - Telegram notifier adapter，包裝現有 `alert_signals.send_message`
- Create: `execution_agent/runner.py`
  - CLI 入口，串起 config、tracking source、quote fetch、decision、notify、state store
- Create: `execution_agent/Dockerfile`
  - VM 上執行 agent 的映像檔
- Create: `execution_agent/docker-compose.yml`
  - 單機部署與 volume 綁定
- Create: `execution_agent/.env.example`
  - 必要環境變數樣板
- Create: `tests/test_execution_agent_tracking_source.py`
  - 驗證 tracking 載入與 pending record 篩選
- Create: `tests/test_execution_agent_open_entry_core.py`
  - 驗證開盤判斷語意
- Create: `tests/test_execution_agent_state_store.py`
  - 驗證 SQLite 去重與 audit write
- Create: `tests/test_execution_agent_runner.py`
  - 驗證 CLI dry-run / notify-run 整體流程
- Create: `tests/test_execution_agent_docs.py`
  - 驗證 README 已包含 Phase 1 啟動文件
- Modify: `send_mwp_c_open_entry_calls.py`
  - 改為重用新的 shared core，避免未來邏輯漂移
- Modify: `README.md`
  - 增加 Phase 1 VM 啟動方式與本地測試指令

### Task 1: 建立正式追蹤 pending 名單載入模組

**Files:**
- Create: `execution_agent/__init__.py`
- Create: `execution_agent/tracking_source.py`
- Create: `tests/test_execution_agent_tracking_source.py`

**Interfaces:**
- Consumes: `reports/mwp_a_strategy_tracking.json` 原始 JSON 結構
- Produces:
  - `PendingOpenEntry` dataclass
  - `load_tracking_payload_from_text(raw_text: str) -> dict[str, Any]`
  - `select_pending_open_entries(payload: dict[str, Any], signal_date: str) -> list[PendingOpenEntry]`

- [ ] **Step 1: 寫 failing test，鎖定 `待次日開盤` 篩選語意**

```python
import unittest

from execution_agent.tracking_source import select_pending_open_entries


class TrackingSourceTests(unittest.TestCase):
    def test_select_pending_open_entries_keeps_only_pending_records(self) -> None:
        payload = {
            "tracking": {
                "formal_forward_records": [
                    {
                        "market": "TWSE",
                        "stock_no": "3094",
                        "stock_name": "聯傑",
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
                        "stock_name": "日電貿",
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
```

- [ ] **Step 2: 執行測試，確認目前失敗**

Run: `python -m unittest tests.test_execution_agent_tracking_source -v`

Expected: `ModuleNotFoundError: No module named 'execution_agent'`

- [ ] **Step 3: 寫最小實作，建立 typed pending record 載入**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PENDING_NEXT_OPEN_STATUS = "待次日開盤"


@dataclass(frozen=True)
class PendingOpenEntry:
    market: str
    stock_no: str
    stock_name: str
    signal_date: str
    entry_limit_price: float
    signal_close: float
    unit_type: str
    addon_number: int | None


def load_tracking_payload_from_text(raw_text: str) -> dict[str, Any]:
    import json

    return json.loads(raw_text)


def select_pending_open_entries(payload: dict[str, Any], signal_date: str) -> list[PendingOpenEntry]:
    rows = payload.get("tracking", {}).get("formal_forward_records", [])
    selected: list[PendingOpenEntry] = []
    for row in rows:
        if str(row.get("status") or "") != PENDING_NEXT_OPEN_STATUS:
            continue
        if str(row.get("signal_date") or "") != signal_date:
            continue
        selected.append(
            PendingOpenEntry(
                market=str(row.get("market") or "").upper(),
                stock_no=str(row.get("stock_no") or ""),
                stock_name=str(row.get("stock_name") or ""),
                signal_date=str(row.get("signal_date") or ""),
                entry_limit_price=float(row.get("entry_limit_price") or 0.0),
                signal_close=float(row.get("signal_close") or 0.0),
                unit_type=str(row.get("unit_type") or "base"),
                addon_number=row.get("addon_number"),
            )
        )
    return selected
```

- [ ] **Step 4: 再跑測試，確認 pending 篩選通過**

Run: `python -m unittest tests.test_execution_agent_tracking_source -v`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add execution_agent/__init__.py execution_agent/tracking_source.py tests/test_execution_agent_tracking_source.py
git commit -m "feat: add execution agent tracking loader"
```

### Task 2: 建立開盤判斷核心與 SQLite call log

**Files:**
- Create: `execution_agent/open_entry_core.py`
- Create: `execution_agent/state_store.py`
- Create: `tests/test_execution_agent_open_entry_core.py`
- Create: `tests/test_execution_agent_state_store.py`

**Interfaces:**
- Consumes: `PendingOpenEntry`
- Produces:
  - `OpenEntryDecision` dataclass
  - `build_open_entry_decision(entry: PendingOpenEntry, open_price: float) -> OpenEntryDecision`
  - `SQLiteStateStore(db_path: str)`
  - `SQLiteStateStore.has_processed(call_key: str) -> bool`
  - `SQLiteStateStore.record_decision(decision: OpenEntryDecision) -> None`

- [ ] **Step 1: 寫 failing test，鎖定 `open_price <= entry_limit_price` 判斷與去重**

```python
import tempfile
import unittest

from execution_agent.open_entry_core import build_open_entry_decision
from execution_agent.state_store import SQLiteStateStore
from execution_agent.tracking_source import PendingOpenEntry


class OpenEntryCoreTests(unittest.TestCase):
    def test_build_open_entry_decision_marks_called_when_open_is_below_limit(self) -> None:
        entry = PendingOpenEntry(
            market="TWSE",
            stock_no="3094",
            stock_name="聯傑",
            signal_date="2026-07-08",
            entry_limit_price=41.65,
            signal_close=42.5,
            unit_type="base",
            addon_number=None,
        )

        decision = build_open_entry_decision(entry, open_price=41.35)

        self.assertEqual(decision.result, "called")
        self.assertEqual(decision.call_key, "TWSE:3094:2026-07-08:base:-")


class StateStoreTests(unittest.TestCase):
    def test_record_decision_makes_call_key_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteStateStore(f"{tmpdir}/agent.db")
            entry = PendingOpenEntry(
                market="TWSE",
                stock_no="3094",
                stock_name="聯傑",
                signal_date="2026-07-08",
                entry_limit_price=41.65,
                signal_close=42.5,
                unit_type="base",
                addon_number=None,
            )
            decision = build_open_entry_decision(entry, open_price=41.35)

            self.assertFalse(store.has_processed(decision.call_key))
            store.record_decision(decision)
            self.assertTrue(store.has_processed(decision.call_key))
```

- [ ] **Step 2: 執行測試，確認核心與 state store 尚未存在**

Run: `python -m unittest tests.test_execution_agent_open_entry_core tests.test_execution_agent_state_store -v`

Expected: import error for `execution_agent.open_entry_core` or `execution_agent.state_store`

- [ ] **Step 3: 寫最小實作，建立 decision dataclass 與 SQLite audit**

```python
from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from execution_agent.tracking_source import PendingOpenEntry


@dataclass(frozen=True)
class OpenEntryDecision:
    call_key: str
    market: str
    stock_no: str
    stock_name: str
    signal_date: str
    entry_limit_price: float
    signal_close: float
    open_price: float
    result: str


def build_open_entry_decision(entry: PendingOpenEntry, open_price: float) -> OpenEntryDecision:
    addon_part = "-" if entry.addon_number in {None, ""} else str(entry.addon_number)
    call_key = f"{entry.market}:{entry.stock_no}:{entry.signal_date}:{entry.unit_type}:{addon_part}"
    result = "called" if open_price <= entry.entry_limit_price else "open_failed"
    return OpenEntryDecision(
        call_key=call_key,
        market=entry.market,
        stock_no=entry.stock_no,
        stock_name=entry.stock_name,
        signal_date=entry.signal_date,
        entry_limit_price=entry.entry_limit_price,
        signal_close=entry.signal_close,
        open_price=open_price,
        result=result,
    )


class SQLiteStateStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists open_entry_calls (
                    call_key text primary key,
                    market text not null,
                    stock_no text not null,
                    signal_date text not null,
                    result text not null,
                    entry_limit_price real not null,
                    open_price real not null,
                    created_at text not null default current_timestamp
                )
                """
            )

    def has_processed(self, call_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("select 1 from open_entry_calls where call_key = ?", (call_key,)).fetchone()
        return row is not None

    def record_decision(self, decision: OpenEntryDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert or ignore into open_entry_calls
                (call_key, market, stock_no, signal_date, result, entry_limit_price, open_price)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.call_key,
                    decision.market,
                    decision.stock_no,
                    decision.signal_date,
                    decision.result,
                    decision.entry_limit_price,
                    decision.open_price,
                ),
            )
```

- [ ] **Step 4: 再跑測試，確認核心與 state store 正常**

Run: `python -m unittest tests.test_execution_agent_open_entry_core tests.test_execution_agent_state_store -v`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add execution_agent/open_entry_core.py execution_agent/state_store.py tests/test_execution_agent_open_entry_core.py tests/test_execution_agent_state_store.py
git commit -m "feat: add open entry core and sqlite state store"
```

### Task 3: 建立 CLI runner，串起 Telegram 與 dry-run / live-run

**Files:**
- Create: `execution_agent/config.py`
- Create: `execution_agent/notifier.py`
- Create: `execution_agent/runner.py`
- Create: `tests/test_execution_agent_runner.py`
- Modify: `send_mwp_c_open_entry_calls.py`

**Interfaces:**
- Consumes:
  - `select_pending_open_entries(...)`
  - `build_open_entry_decision(...)`
  - `SQLiteStateStore`
- Produces:
  - `ExecutionAgentConfig.from_env() -> ExecutionAgentConfig`
  - `TelegramNotifier.send_open_entry_call(decision: OpenEntryDecision) -> bool`
  - `run_open_entry_cycle(...) -> list[OpenEntryDecision]`

- [ ] **Step 1: 寫 failing test，鎖定 dry-run 與 notify-run 行為**

```python
import tempfile
import unittest

from execution_agent.open_entry_core import build_open_entry_decision
from execution_agent.runner import run_open_entry_cycle
from execution_agent.tracking_source import PendingOpenEntry


class FakeNotifier:
    def __init__(self) -> None:
        self.sent = []

    def send_open_entry_call(self, decision) -> bool:
        self.sent.append(decision.call_key)
        return True


class RunnerTests(unittest.TestCase):
    def test_run_open_entry_cycle_records_called_and_sends_notification(self) -> None:
        entries = [
            PendingOpenEntry(
                market="TWSE",
                stock_no="3094",
                stock_name="聯傑",
                signal_date="2026-07-08",
                entry_limit_price=41.65,
                signal_close=42.5,
                unit_type="base",
                addon_number=None,
            )
        ]

        def quote_lookup(entry: PendingOpenEntry) -> float:
            return 41.35

        notifier = FakeNotifier()
        with tempfile.TemporaryDirectory() as tmpdir:
            decisions = run_open_entry_cycle(
                entries=entries,
                quote_lookup=quote_lookup,
                notifier=notifier,
                db_path=f"{tmpdir}/agent.db",
                dry_run=False,
            )

        self.assertEqual([item.result for item in decisions], ["called"])
        self.assertEqual(notifier.sent, ["TWSE:3094:2026-07-08:base:-"])
```

- [ ] **Step 2: 執行測試，確認 runner 與 notifier 尚未存在**

Run: `python -m unittest tests.test_execution_agent_runner -v`

Expected: import error for `execution_agent.runner`

- [ ] **Step 3: 寫最小實作，建立 config / notifier / runner，並讓舊 script 重用核心**

```python
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable

from alert_signals import send_message
from execution_agent.open_entry_core import OpenEntryDecision, build_open_entry_decision
from execution_agent.state_store import SQLiteStateStore
from execution_agent.tracking_source import PendingOpenEntry


@dataclass(frozen=True)
class ExecutionAgentConfig:
    tracking_json_url: str
    state_db_path: str
    signal_date: str
    dry_run: bool

    @classmethod
    def from_env(cls) -> "ExecutionAgentConfig":
        return cls(
            tracking_json_url=os.environ["TRACKING_JSON_URL"],
            state_db_path=os.environ.get("STATE_DB_PATH", "./state/agent.db"),
            signal_date=os.environ["SIGNAL_DATE"],
            dry_run=os.environ.get("DRY_RUN", "0") == "1",
        )


class TelegramNotifier:
    def send_open_entry_call(self, decision: OpenEntryDecision) -> bool:
        message = "\n".join(
            [
                "🚨 MWP-C 正式追蹤",
                f"🏷️ {decision.stock_no} {decision.stock_name}",
                f"📅 訊號日 {decision.signal_date}",
                f"🎯 進場上限 {decision.entry_limit_price}",
                f"🟢 次日開盤 {decision.open_price}",
            ]
        )
        return "telegram" in send_message(message, channels={"telegram"})


def run_open_entry_cycle(
    entries: list[PendingOpenEntry],
    quote_lookup: Callable[[PendingOpenEntry], float],
    notifier: TelegramNotifier,
    db_path: str,
    dry_run: bool,
) -> list[OpenEntryDecision]:
    store = SQLiteStateStore(db_path)
    decisions: list[OpenEntryDecision] = []
    for entry in entries:
        decision = build_open_entry_decision(entry, open_price=quote_lookup(entry))
        if store.has_processed(decision.call_key):
            continue
        if not dry_run and decision.result == "called":
            notifier.send_open_entry_call(decision)
        if not dry_run:
            store.record_decision(decision)
        decisions.append(decision)
    return decisions
```

- [ ] **Step 4: 執行 runner 測試與既有 script 回歸測試**

Run: `python -m unittest tests.test_execution_agent_runner tests.test_verify_mwp_c_forward_records -v`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add execution_agent/config.py execution_agent/notifier.py execution_agent/runner.py tests/test_execution_agent_runner.py send_mwp_c_open_entry_calls.py
git commit -m "feat: add execution agent runner"
```

### Task 4: 加入 GCP VM 部署資產與操作文件

**Files:**
- Create: `execution_agent/Dockerfile`
- Create: `execution_agent/docker-compose.yml`
- Create: `execution_agent/.env.example`
- Create: `tests/test_execution_agent_docs.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `execution_agent.runner`
- Produces:
  - `docker compose up -d execution-agent`
  - 可在 GCP VM 透過 `.env` 啟動的單機部署方式

- [ ] **Step 1: 寫 failing documentation check，先鎖定 README 必須出現 Phase 1 啟動指令**

```python
import pathlib
import unittest


class ReadmeExecutionAgentDocsTests(unittest.TestCase):
    def test_readme_mentions_execution_agent_compose_command(self) -> None:
        text = pathlib.Path("README.md").read_text(encoding="utf-8")
        self.assertIn("docker compose up -d execution-agent", text)
        self.assertIn("TRACKING_JSON_URL", text)
```

- [ ] **Step 2: 執行文件檢查，確認 README 尚未包含 GCP 啟動說明**

Run: `python -m unittest tests.test_execution_agent_docs -v`

Expected: FAIL with missing README text

- [ ] **Step 3: 新增 Docker 與 `.env` 樣板，補上 README 啟動文件**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "execution_agent.runner"]
```

```yaml
services:
  execution-agent:
    build:
      context: ..
      dockerfile: execution_agent/Dockerfile
    env_file:
      - .env
    volumes:
      - ./state:/app/state
    restart: unless-stopped
```

```env
TRACKING_JSON_URL=https://raw.githubusercontent.com/sarsadsl/daily_stock_signal/main/reports/mwp_a_strategy_tracking.json
STATE_DB_PATH=/app/state/agent.db
SIGNAL_DATE=2026-07-08
DRY_RUN=1
```

```markdown
### Execution Agent Phase 1

1. Copy `execution_agent/.env.example` to `execution_agent/.env`
2. Set `TRACKING_JSON_URL`, `STATE_DB_PATH`, and `SIGNAL_DATE`
3. Start the container:

```bash
cd execution_agent
docker compose up -d execution-agent
```
```

- [ ] **Step 4: 執行文件檢查與基本語法檢查**

Run: `python -m unittest tests.test_execution_agent_docs -v`

Expected: `OK`

Run: `python -m py_compile execution_agent/config.py execution_agent/tracking_source.py execution_agent/open_entry_core.py execution_agent/state_store.py execution_agent/notifier.py execution_agent/runner.py`

Expected: no output

- [ ] **Step 5: Commit**

```bash
git add execution_agent/Dockerfile execution_agent/docker-compose.yml execution_agent/.env.example README.md tests/test_execution_agent_docs.py
git commit -m "docs: add execution agent deployment assets"
```

## Self-Review

- **Spec coverage:** 本計畫只涵蓋 spec 的 Phase 1，包含 GCP VM 部署、正式追蹤 JSON 同步、開盤判斷、Telegram call、SQLite 狀態保存與 deployment 文件；刻意不含 sandbox/live order 與 broker WebSocket，符合 spec 的分階段要求。
- **Placeholder scan:** 本計畫未使用 `TBD`、`TODO`、`implement later`、`similar to task N` 等占位描述。
- **Type consistency:** `PendingOpenEntry`、`OpenEntryDecision`、`SQLiteStateStore`、`TelegramNotifier`、`run_open_entry_cycle` 名稱在各 task 間一致，後續 task 只依賴前面明確定義的介面。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-09-mwp-c-execution-agent-phase1.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
