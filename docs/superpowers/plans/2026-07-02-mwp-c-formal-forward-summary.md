# MWP-C Formal Forward Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a forward-only `正式追蹤專屬` summary to `mwp_c_realized_pnl.html` using only `tracking.formal_forward_records`.

**Architecture:** Put the forward-summary semantics in `mwp_c_strategy_helpers.js` so both MWP-C pages share the same definition of what counts as an active formal forward row. Then render one additional metric section in `mwp_c_realized_pnl.html` without changing the existing realized/unrealized trade list.

**Tech Stack:** Static HTML, browser JavaScript, Node test runner, PowerShell site build

## Global Constraints

- The new summary must use only `tracking.formal_forward_records`.
- Only active formal forward rows count; pending and failed-entry rows must be excluded.
- The existing historical realized/unrealized stock-group list must stay intact.
- Tests must follow TDD and prove the forward-summary helper behavior before implementation.

---

### Task 1: Add Forward Summary Helper Coverage

**Files:**
- Modify: `C:\Users\Wei&Ting\Documents\Codex\2026-06-10\git-daily-stock-signal-etf-track-worktrees\mwp-c-formal-forward-display\tests\test_mwp_c_strategy_helpers.js`
- Modify: `C:\Users\Wei&Ting\Documents\Codex\2026-06-10\git-daily-stock-signal-etf-track-worktrees\mwp-c-formal-forward-display\mwp_c_strategy_helpers.js`

**Interfaces:**
- Consumes: existing `isActiveForwardStatus(status)` helper
- Produces: `buildFormalForwardSummary(records)` returning
  `{ totalCount, realizedCount, unrealizedCount, realizedWinRate, realizedAverageReturnPct, realizedTotalPnl, unrealizedTotalPnl }`

- [ ] **Step 1: Write the failing test**

```javascript
test("buildFormalForwardSummary counts only active formal rows", () => {
  const rows = [
    { status: "open", pnl: 1200, return_pct: 12, exit_date: "" },
    { status: "exited", pnl: 500, return_pct: 5, exit_date: "2026-07-01" },
    { status: "exited", pnl: -300, return_pct: -3, exit_date: "2026-07-02" },
    { status: "entry_filter_failed", pnl: 9999, return_pct: 99, exit_date: "" },
    { status: "pending", pnl: 9999, return_pct: 99, exit_date: "" },
  ];

  assert.deepEqual(buildFormalForwardSummary(rows), {
    totalCount: 3,
    realizedCount: 2,
    unrealizedCount: 1,
    realizedWinRate: 50,
    realizedAverageReturnPct: 1,
    realizedTotalPnl: 200,
    unrealizedTotalPnl: 1200,
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: FAIL because `buildFormalForwardSummary` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```javascript
function buildFormalForwardSummary(records) {
  const activeRows = [...(records || [])].filter((row) =>
    isActiveForwardStatus(row?.status)
  );
  const realizedRows = activeRows.filter((row) => String(row?.exit_date || ""));
  const unrealizedRows = activeRows.filter((row) => !String(row?.exit_date || ""));
  const realizedReturns = realizedRows.map((row) => Number(row?.return_pct) || 0);
  const realizedWins = realizedRows.filter((row) => (Number(row?.return_pct) || 0) >= 0);

  return {
    totalCount: activeRows.length,
    realizedCount: realizedRows.length,
    unrealizedCount: unrealizedRows.length,
    realizedWinRate: realizedRows.length ? (realizedWins.length / realizedRows.length) * 100 : null,
    realizedAverageReturnPct: realizedRows.length ? realizedReturns.reduce((sum, value) => sum + value, 0) / realizedRows.length : null,
    realizedTotalPnl: realizedRows.reduce((sum, row) => sum + (Number(row?.pnl) || 0), 0),
    unrealizedTotalPnl: unrealizedRows.reduce((sum, row) => sum + (Number(row?.pnl) || 0), 0),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_mwp_c_strategy_helpers.js mwp_c_strategy_helpers.js
git commit -m "Add formal forward summary helper"
```

### Task 2: Render Forward-Only Summary On The Realized PnL Page

**Files:**
- Modify: `C:\Users\Wei&Ting\Documents\Codex\2026-06-10\git-daily-stock-signal-etf-track-worktrees\mwp-c-formal-forward-display\mwp_c_realized_pnl.html`
- Modify: `C:\Users\Wei&Ting\Documents\Codex\2026-06-10\git-daily-stock-signal-etf-track-worktrees\mwp-c-formal-forward-display\build_site.ps1`

**Interfaces:**
- Consumes: `window.mwpCStrategyHelpers.buildFormalForwardSummary(records)`
- Produces: extra summary cards on `mwp_c_realized_pnl.html`

- [ ] **Step 1: Write the failing UI contract check**

```javascript
assert.match(html, /正式追蹤專屬/);
assert.match(html, /forwardSummary/);
assert.match(html, /buildFormalForwardSummary/);
```

- [ ] **Step 2: Run targeted verification to confirm the page does not yet contain the new summary**

Run: `rg -n "正式追蹤專屬|forwardSummary|buildFormalForwardSummary" mwp_c_realized_pnl.html`
Expected: no `正式追蹤專屬` summary wiring yet

- [ ] **Step 3: Implement the page wiring**

```html
<script src="mwp_c_strategy_helpers.js"></script>
```

```javascript
const forwardSummary = window.mwpCStrategyHelpers.buildFormalForwardSummary(
  payload.tracking?.formal_forward_records || []
);
renderForwardSummary(forwardSummary);
```

```javascript
function renderForwardSummary(summary) {
  // populate the dedicated formal-forward summary cards
}
```

- [ ] **Step 4: Run build and helper tests**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: PASS

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File build_site.ps1`
Expected: `Built static site at ...\site`

- [ ] **Step 5: Commit**

```bash
git add mwp_c_realized_pnl.html build_site.ps1
git commit -m "Show formal forward summary on realized pnl page"
```

### Task 3: Final Verification

**Files:**
- Verify only

**Interfaces:**
- Consumes: Task 1 helper and Task 2 page wiring
- Produces: evidence that the feature works and builds cleanly

- [ ] **Step 1: Run the full relevant test suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS with all Python tests green

- [ ] **Step 2: Run the Node helper tests**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: PASS

- [ ] **Step 3: Run the site build**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File build_site.ps1`
Expected: `Built static site at ...\site`

- [ ] **Step 4: Run diff hygiene**

Run: `git diff --check`
Expected: no patch-format errors beyond existing CRLF warnings if any

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Finalize formal forward summary verification"
```
