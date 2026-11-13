# MWP-C Shioaji Sandbox Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Phase 2 sandbox execution adapter，讓 Phase 1 的 MWP-C 正式追蹤 `called` 決策可以安全同步成永豐 Shioaji sandbox order 與 SQLite sandbox ledger。

**Architecture:** 新增 broker 設定、下單 sizing、sandbox ledger、broker adapter、sandbox executor 五個小模組，並在 runner 末端以可選方式串接。預設 `BROKER_MODE=noop`，所以既有 Phase 1 call 行為不變；只有 `BROKER_MODE=sandbox` 且 `SANDBOX_ONLY=1` 時才會送 Shioaji simulation order。

**Tech Stack:** Python 3.12、`unittest`、`sqlite3`、lazy import `shioaji`、現有 `execution_agent.runner` 與 `OpenEntryDecision`。

## Global Constraints

- 不送正式單；`BROKER_MODE=live` 必須拒絕啟動。
- 不修改 `reports/mwp_a_strategy_tracking.json` 的正式追蹤判斷。
- 不修改現有網頁正式追蹤顯示邏輯。
- 不自行重新判斷進出場條件；進場只吃 Phase 1 `called` 決策。
- 不在 git、報告或 log 內輸出 API key、secret、session token、帳號或憑證內容。
- 預設 `BROKER_MODE=noop`，不送任何 broker order。
- `BROKER_MODE=sandbox` 時必須同時有 `SANDBOX_ONLY=1`、`SHIOAJI_API_KEY`、`SHIOAJI_SECRET_KEY`。
- Phase 2 初版只處理買進 sandbox order；出場與 WebSocket 監控留到 Phase 3。

---

## File Structure

- Create: `execution_agent/broker_config.py`
  - 讀取 broker mode、sandbox-only guard、Shioaji key/secret、單筆預算與 lot mode。
- Create: `execution_agent/order_sizing.py`
  - 將 `OpenEntryDecision` 轉成 `SandboxOrderRequest`，並處理預算不足。
- Create: `execution_agent/broker_adapter.py`
  - 定義 `SandboxOrderRequest`、`SandboxOrderResult`、`BrokerAdapter`、`NoopBrokerAdapter`、`ShioajiSandboxBrokerAdapter`。
- Create: `execution_agent/sandbox_ledger.py`
  - SQLite sandbox orders / positions / events 資料表與冪等查詢。
- Create: `execution_agent/sandbox_executor.py`
  - 接收 decisions，過濾 `called`，做 sizing、ledger duplicate guard、送 broker、寫 ledger。
- Modify: `execution_agent/runner.py`
  - 在 Phase 1 decisions 產生後，依 env 決定是否執行 sandbox executor。
- Modify: `execution_agent/.env.example`
  - 補 broker sandbox 相關環境變數。
- Modify: `README.md`
  - 補 sandbox adapter 使用方式與安全邊界。
- Create: `tests/test_execution_agent_broker_config.py`
- Create: `tests/test_execution_agent_order_sizing.py`
- Create: `tests/test_execution_agent_sandbox_ledger.py`
- Create: `tests/test_execution_agent_sandbox_executor.py`
- Extend: `tests/test_execution_agent_runner.py`
- Extend: `tests/test_execution_agent_docs.py`

### Task 1: Broker Config Safety

**Files:**
- Create: `execution_agent/broker_config.py`
- Create: `tests/test_execution_agent_broker_config.py`

**Interfaces:**
- Produces:
  - `BrokerConfigError(ValueError)`
  - `BrokerConfig` dataclass with fields `broker_mode: str`, `sandbox_only: bool`, `shioaji_api_key: str | None`, `shioaji_secret_key: str | None`, `order_cash_per_trade: float`, `order_lot_mode: str`
  - `BrokerConfig.from_env(environ: Mapping[str, str] | None = None) -> BrokerConfig`
  - `BrokerConfig.should_submit_orders() -> bool`

- [ ] **Step 1: Write failing broker config tests**

```python
import unittest

from execution_agent.broker_config import BrokerConfig, BrokerConfigError


class BrokerConfigTests(unittest.TestCase):
    def test_defaults_to_noop_without_credentials(self) -> None:
        config = BrokerConfig.from_env({})

        self.assertEqual(config.broker_mode, "noop")
        self.assertFalse(config.should_submit_orders())
        self.assertEqual(config.order_cash_per_trade, 100000.0)

    def test_rejects_live_mode(self) -> None:
        with self.assertRaisesRegex(BrokerConfigError, "live"):
            BrokerConfig.from_env({"BROKER_MODE": "live"})

    def test_sandbox_requires_sandbox_only_and_credentials(self) -> None:
        with self.assertRaisesRegex(BrokerConfigError, "SANDBOX_ONLY"):
            BrokerConfig.from_env(
                {
                    "BROKER_MODE": "sandbox",
                    "SHIOAJI_API_KEY": "key",
                    "SHIOAJI_SECRET_KEY": "secret",
                }
            )

        with self.assertRaisesRegex(BrokerConfigError, "SHIOAJI_API_KEY"):
            BrokerConfig.from_env({"BROKER_MODE": "sandbox", "SANDBOX_ONLY": "1"})

    def test_accepts_sandbox_mode_when_guarded(self) -> None:
        config = BrokerConfig.from_env(
            {
                "BROKER_MODE": "sandbox",
                "SANDBOX_ONLY": "1",
                "SHIOAJI_API_KEY": "key",
                "SHIOAJI_SECRET_KEY": "secret",
                "ORDER_CASH_PER_TRADE": "50000",
            }
        )

        self.assertTrue(config.should_submit_orders())
        self.assertEqual(config.order_cash_per_trade, 50000.0)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_execution_agent_broker_config -v`

Expected: fails with `ModuleNotFoundError` or import error for `execution_agent.broker_config`.

- [ ] **Step 3: Implement broker config**

Add a small dataclass that normalizes `BROKER_MODE` to lowercase, defaults to `noop`, rejects unsupported modes, rejects `live`, and validates sandbox credentials without printing values.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_execution_agent_broker_config -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add execution_agent/broker_config.py tests/test_execution_agent_broker_config.py
git commit -m "feat: add broker config safety guards"
```

### Task 2: Order Sizing

**Files:**
- Create: `execution_agent/order_sizing.py`
- Create: `tests/test_execution_agent_order_sizing.py`

**Interfaces:**
- Consumes:
  - `OpenEntryDecision` from `execution_agent.open_entry_core`
  - `SandboxOrderRequest` from `execution_agent.broker_adapter`
- Produces:
  - `OrderSizingError(ValueError)`
  - `build_buy_order_request(decision: OpenEntryDecision, cash_budget: float) -> SandboxOrderRequest`

- [ ] **Step 1: Write failing order sizing tests**

```python
import unittest

from execution_agent.open_entry_core import build_open_entry_decision
from execution_agent.order_sizing import OrderSizingError, build_buy_order_request
from execution_agent.tracking_source import PendingOpenEntry


def called_decision():
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
    return build_open_entry_decision(entry, open_price=41.35)


class OrderSizingTests(unittest.TestCase):
    def test_builds_buy_request_without_exceeding_cash_budget(self) -> None:
        request = build_buy_order_request(called_decision(), cash_budget=100000)

        self.assertEqual(request.call_key, "TWSE:3094:2026-07-08:base:-")
        self.assertEqual(request.stock_no, "3094")
        self.assertEqual(request.quantity, 2418)
        self.assertEqual(request.price, 41.35)
        self.assertLessEqual(request.quantity * request.price, 100000)

    def test_rejects_non_called_decision(self) -> None:
        decision = called_decision()
        failed = type(decision)(**{**decision.__dict__, "result": "open_failed"})

        with self.assertRaisesRegex(OrderSizingError, "called"):
            build_buy_order_request(failed, cash_budget=100000)

    def test_rejects_budget_too_small_for_one_share(self) -> None:
        with self.assertRaisesRegex(OrderSizingError, "quantity"):
            build_buy_order_request(called_decision(), cash_budget=10)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_execution_agent_order_sizing -v`

Expected: fails because `execution_agent.order_sizing` and `execution_agent.broker_adapter` are missing.

- [ ] **Step 3: Implement broker dataclasses and sizing**

Create `SandboxOrderRequest` / `SandboxOrderResult` first in `broker_adapter.py`, then implement `build_buy_order_request(...)` with integer quantity floor and `order_type="sandbox_buy_open"`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_execution_agent_order_sizing -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add execution_agent/broker_adapter.py execution_agent/order_sizing.py tests/test_execution_agent_order_sizing.py
git commit -m "feat: add sandbox order sizing"
```

### Task 3: Sandbox Ledger

**Files:**
- Create: `execution_agent/sandbox_ledger.py`
- Create: `tests/test_execution_agent_sandbox_ledger.py`

**Interfaces:**
- Consumes:
  - `SandboxOrderRequest`
  - `SandboxOrderResult`
- Produces:
  - `SandboxLedger(db_path: str)`
  - `SandboxLedger.has_order(call_key: str) -> bool`
  - `SandboxLedger.record_order(request: SandboxOrderRequest, result: SandboxOrderResult) -> None`
  - `SandboxLedger.record_event(call_key: str, event_type: str, message: str) -> None`
  - `SandboxLedger.list_orders() -> list[dict[str, object]]`
  - `SandboxLedger.list_positions() -> list[dict[str, object]]`
  - `SandboxLedger.list_events() -> list[dict[str, object]]`

- [ ] **Step 1: Write failing ledger tests**

```python
import tempfile
import unittest
from pathlib import Path

from execution_agent.broker_adapter import SandboxOrderRequest, SandboxOrderResult
from execution_agent.sandbox_ledger import SandboxLedger


class SandboxLedgerTests(unittest.TestCase):
    def test_record_order_creates_order_and_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            request = SandboxOrderRequest(
                call_key="TWSE:3094:2026-07-08:base:-",
                market="TWSE",
                stock_no="3094",
                stock_name="聯傑",
                signal_date="2026-07-08",
                open_price=41.35,
                entry_limit_price=41.65,
                cash_budget=100000,
                quantity=2418,
                price=41.35,
                order_type="sandbox_buy_open",
            )
            result = SandboxOrderResult(
                call_key=request.call_key,
                accepted=True,
                broker_order_id="sandbox-1",
                submitted_at="2026-07-10T09:00:00+08:00",
                message="accepted",
            )

            ledger.record_order(request, result)

            self.assertTrue(ledger.has_order(request.call_key))
            self.assertEqual(len(ledger.list_orders()), 1)
            self.assertEqual(len(ledger.list_positions()), 1)

    def test_record_event_does_not_create_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))

            ledger.record_event("key-1", "broker_error", "submit failed")

            self.assertEqual(len(ledger.list_events()), 1)
            self.assertEqual(ledger.list_positions(), [])
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_execution_agent_sandbox_ledger -v`

Expected: fails because `execution_agent.sandbox_ledger` is missing.

- [ ] **Step 3: Implement SQLite ledger**

Create tables `sandbox_orders`, `sandbox_positions`, `sandbox_events`. Use `call_key TEXT UNIQUE` for `sandbox_orders`; only accepted results create positions.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_execution_agent_sandbox_ledger -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add execution_agent/sandbox_ledger.py tests/test_execution_agent_sandbox_ledger.py
git commit -m "feat: add sandbox ledger"
```

### Task 4: Sandbox Executor With Fake Broker

**Files:**
- Modify: `execution_agent/broker_adapter.py`
- Create: `execution_agent/sandbox_executor.py`
- Create: `tests/test_execution_agent_sandbox_executor.py`

**Interfaces:**
- Consumes:
  - `BrokerConfig`
  - `OpenEntryDecision`
  - `SandboxLedger`
  - `build_buy_order_request(...)`
- Produces:
  - `BrokerAdapter.submit_buy_order(request: SandboxOrderRequest) -> SandboxOrderResult`
  - `NoopBrokerAdapter`
  - `ShioajiSandboxBrokerAdapter`
  - `SandboxExecutionSummary` dataclass
  - `execute_sandbox_orders(decisions: list[OpenEntryDecision], config: BrokerConfig, ledger: SandboxLedger, broker: BrokerAdapter | None = None) -> SandboxExecutionSummary`

- [ ] **Step 1: Write failing executor tests**

```python
import tempfile
import unittest
from pathlib import Path

from execution_agent.broker_adapter import SandboxOrderResult
from execution_agent.broker_config import BrokerConfig
from execution_agent.open_entry_core import build_open_entry_decision
from execution_agent.sandbox_executor import execute_sandbox_orders
from execution_agent.sandbox_ledger import SandboxLedger
from execution_agent.tracking_source import PendingOpenEntry


class FakeBroker:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.requests = []

    def submit_buy_order(self, request):
        self.requests.append(request)
        return SandboxOrderResult(
            call_key=request.call_key,
            accepted=self.accepted,
            broker_order_id=f"fake-{len(self.requests)}",
            submitted_at="2026-07-10T09:00:00+08:00",
            message="accepted" if self.accepted else "rejected",
        )


def decision(stock_no="3094", open_price=41.35, limit=41.65):
    entry = PendingOpenEntry(
        market="TWSE",
        stock_no=stock_no,
        stock_name="聯傑",
        signal_date="2026-07-08",
        entry_limit_price=limit,
        signal_close=42.5,
        unit_type="base",
        addon_number=None,
    )
    return build_open_entry_decision(entry, open_price=open_price)


class SandboxExecutorTests(unittest.TestCase):
    def sandbox_config(self) -> BrokerConfig:
        return BrokerConfig.from_env(
            {
                "BROKER_MODE": "sandbox",
                "SANDBOX_ONLY": "1",
                "SHIOAJI_API_KEY": "key",
                "SHIOAJI_SECRET_KEY": "secret",
            }
        )

    def test_submits_only_called_decisions_and_records_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            broker = FakeBroker()
            called = decision()
            failed = decision(stock_no="3090", open_price=300, limit=297.43)

            summary = execute_sandbox_orders(
                [called, failed],
                config=self.sandbox_config(),
                ledger=ledger,
                broker=broker,
            )

            self.assertEqual(summary.submitted, 1)
            self.assertEqual(summary.skipped_non_called, 1)
            self.assertEqual(len(broker.requests), 1)
            self.assertEqual(len(ledger.list_orders()), 1)
            self.assertEqual(len(ledger.list_positions()), 1)

    def test_duplicate_call_key_is_not_resubmitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
            broker = FakeBroker()
            config = self.sandbox_config()

            execute_sandbox_orders([decision()], config=config, ledger=ledger, broker=broker)
            summary = execute_sandbox_orders([decision()], config=config, ledger=ledger, broker=broker)

            self.assertEqual(summary.skipped_duplicate, 1)
            self.assertEqual(len(broker.requests), 1)
            self.assertEqual(len(ledger.list_orders()), 1)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_execution_agent_sandbox_executor -v`

Expected: fails because `execution_agent.sandbox_executor` is missing.

- [ ] **Step 3: Implement executor and adapters**

Implement fake-friendly executor first. `ShioajiSandboxBrokerAdapter` must lazy-import `shioaji`, call `sj.Shioaji(simulation=True)`, login with config credentials, resolve `api.Contracts.Stocks[stock_no]`, submit a buy order, and logout. Do not print credentials.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_execution_agent_sandbox_executor -v`

Expected: all tests pass with fake broker.

- [ ] **Step 5: Commit**

```powershell
git add execution_agent/broker_adapter.py execution_agent/sandbox_executor.py tests/test_execution_agent_sandbox_executor.py
git commit -m "feat: execute sandbox orders from called decisions"
```

### Task 5: Runner Integration And Docs

**Files:**
- Modify: `execution_agent/runner.py`
- Modify: `execution_agent/.env.example`
- Modify: `README.md`
- Modify: `tests/test_execution_agent_runner.py`
- Modify: `tests/test_execution_agent_docs.py`

**Interfaces:**
- Consumes:
  - `BrokerConfig.from_env()`
  - `SandboxLedger`
  - `execute_sandbox_orders(...)`
- Produces:
  - `run_from_config(..., broker_config: BrokerConfig | None = None, sandbox_ledger: SandboxLedger | None = None, broker: BrokerAdapter | None = None) -> list[OpenEntryDecision]`
  - Env-driven runner calls sandbox executor only when `not config.dry_run` and `broker_config.should_submit_orders()`

- [ ] **Step 1: Write failing runner/docs tests**

Extend `tests/test_execution_agent_runner.py`:

```python
def test_run_from_config_executes_sandbox_orders_when_enabled(self) -> None:
    payload_text = json.dumps(
        {
            "tracking": {
                "formal_forward_records": [
                    {
                        "market": "TWSE",
                        "stock_no": "3094",
                        "stock_name": "聯傑",
                        "signal_date": "2026-07-08",
                        "status": PENDING_NEXT_OPEN_STATUS,
                        "entry_limit_price": 41.65,
                        "signal_close": 42.5,
                        "unit_type": "base",
                        "addon_number": None,
                    }
                ]
            }
        }
    )
    config = runner.ExecutionAgentConfig(
        tracking_json_url="https://example.test/tracking.json",
        state_db_path="state/agent.db",
        signal_date="2026-07-09",
        dry_run=False,
    )
    broker_config = runner.BrokerConfig.from_env(
        {
            "BROKER_MODE": "sandbox",
            "SANDBOX_ONLY": "1",
            "SHIOAJI_API_KEY": "key",
            "SHIOAJI_SECRET_KEY": "secret",
        }
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        ledger = runner.SandboxLedger(str(Path(tmpdir) / "sandbox.db"))
        broker = FakeBroker()
        with patch.object(runner, "load_tracking_payload_text", return_value=payload_text):
            with patch.object(
                runner,
                "build_trading_dates",
                return_value={("TWSE", "3094"): ["2026-07-08", "2026-07-09"]},
                create=True,
            ):
                with patch.object(
                    runner,
                    "wait_for_realtime_open_snapshot",
                    return_value={("TWSE", "3094"): 41.35},
                    create=True,
                ):
                    decisions = runner.run_from_config(
                        config,
                        notifier=FakeNotifier(),
                        broker_config=broker_config,
                        sandbox_ledger=ledger,
                        broker=broker,
                    )

        self.assertEqual([item.result for item in decisions], ["called"])
        self.assertEqual(len(broker.requests), 1)
        self.assertEqual(len(ledger.list_orders()), 1)
```

Extend `tests/test_execution_agent_docs.py`:

```python
def test_env_example_documents_sandbox_broker_safety(self) -> None:
    text = pathlib.Path("execution_agent/.env.example").read_text(encoding="utf-8")
    self.assertIn("BROKER_MODE=noop", text)
    self.assertIn("SANDBOX_ONLY=1", text)
    self.assertIn("SHIOAJI_API_KEY=", text)
    self.assertIn("SHIOAJI_SECRET_KEY=", text)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_execution_agent_runner tests.test_execution_agent_docs -v`

Expected: fails because runner/docs do not yet wire broker config or env examples.

- [ ] **Step 3: Implement runner integration and docs**

Add optional dependency-injection parameters to `run_from_config` and `run_from_env`. Use `STATE_DB_PATH` as the default sandbox ledger DB path unless a ledger is injected. Keep dry-run behavior no-write/no-notify/no-broker.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_execution_agent_runner tests.test_execution_agent_docs -v`

Expected: all tests pass.

- [ ] **Step 5: Full verification**

Run:

```powershell
python -m py_compile execution_agent/broker_config.py execution_agent/broker_adapter.py execution_agent/order_sizing.py execution_agent/sandbox_ledger.py execution_agent/sandbox_executor.py execution_agent/runner.py
python -m unittest discover -s tests -v
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add execution_agent/runner.py execution_agent/.env.example README.md tests/test_execution_agent_runner.py tests/test_execution_agent_docs.py
git commit -m "feat: wire sandbox execution into runner"
```

## Self-Review

- Spec coverage: Plan covers sandbox-only config, Shioaji sandbox adapter, order sizing, SQLite ledger, executor idempotency, runner integration, docs, and tests. It intentionally leaves live order, exit order, and WebSocket monitoring out of scope.
- Placeholder scan: No unfinished-marker language remains. Task 5 includes a concrete runner test skeleton aligned to the existing patch-heavy runner tests.
- Type consistency: `SandboxOrderRequest`, `SandboxOrderResult`, `BrokerConfig`, `SandboxLedger`, and `execute_sandbox_orders` are introduced before runner consumes them.

## Execution Mode

User has already requested: write implementation plan, then continue implementation. Proceed with inline execution using `executing-plans`, TDD, and per-task commits.
