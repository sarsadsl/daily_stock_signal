# Daily Signal Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile report-only freshness check with a tested verifier that validates latest synced market data and logs actionable diagnostics.

**Architecture:** Add a standalone verifier module that computes latest-date market statistics from `run_market_backtest` helpers, then update the workflow to call that module instead of the current inline Python snippet. Keep the workflow interface small by passing only the expected date, and cover the behavior with unit tests.

**Tech Stack:** Python 3.12, `unittest`, GitHub Actions YAML

## Global Constraints

- Reuse existing signal logic from `run_market_backtest`.
- Preserve Taipei weekend skip behavior.
- Fail loudly on zero latest-date signals.
- Emit diagnostics useful for postmortem triage.

---

### Task 1: Add failing verifier tests

**Files:**
- Create: `tests/test_verify_daily_signal_freshness.py`
- Test: `tests/test_verify_daily_signal_freshness.py`

**Interfaces:**
- Consumes: planned `verify_daily_signal_freshness.verify_freshness(expected_date: str, now: datetime | None = None) -> dict[str, object]`
- Produces: failing tests that define expected verifier outputs and failures

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run the verifier test file to confirm failure**
- [ ] **Step 3: Confirm the failure is due to the missing verifier module/function**

### Task 2: Implement the verifier script

**Files:**
- Create: `verify_daily_signal_freshness.py`
- Modify: `tests/test_verify_daily_signal_freshness.py`

**Interfaces:**
- Consumes: `run_market_backtest.csv_files`, `run_market_backtest.read_rows`, `run_market_backtest.prepare`, `run_market_backtest.STRATEGIES`
- Produces: `verify_freshness(...)`, CLI `main()`, and diagnostic printing used by the workflow

- [ ] **Step 1: Implement the smallest verifier logic needed to satisfy the failing tests**
- [ ] **Step 2: Run the verifier tests and make them pass**
- [ ] **Step 3: Refine diagnostic messages without changing verified behavior**

### Task 3: Wire the workflow to the verifier

**Files:**
- Modify: `.github/workflows/daily-signal.yml`
- Modify: `tests/test_verify_mwp_c_forward_records.py`

**Interfaces:**
- Consumes: verifier CLI `python verify_daily_signal_freshness.py --expected-date "${{ inputs.as_of }}"`
- Produces: workflow invocation and ordering coverage

- [ ] **Step 1: Replace the inline freshness Python block with the verifier command**
- [ ] **Step 2: Extend workflow-order coverage if needed**
- [ ] **Step 3: Run targeted tests covering workflow expectations**

### Task 4: Run final verification

**Files:**
- Modify: `CODEX_HANDOFF.md`

**Interfaces:**
- Consumes: completed code and tests
- Produces: fresh verification evidence and updated handoff context

- [ ] **Step 1: Run the targeted unit-test command**
- [ ] **Step 2: Run Python compilation for the new verifier and tests**
- [ ] **Step 3: Update `CODEX_HANDOFF.md` with the fix and verification results**
