# MWP-C Realized PnL Formal Stock List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `正式追蹤` stock-trade list to `mwp_c_realized_pnl.html` so the page can browse active formal-tracking holdings/exits alongside the existing historical list and shared K-line chart.

**Architecture:** Keep the existing page layout intact, add a small left-panel tab switch, and build the new formal-tracking dataset from `tracking.formal_forward_records` through shared helper logic in `mwp_c_strategy_helpers.js`. The realized-PnL page will choose between historical groups and formal groups based on the selected tab while reusing the current search, card list, selection state, and chart renderer.

**Tech Stack:** Static HTML, browser JavaScript, Node test runner, Python unittest, PowerShell site build

## Global Constraints

- The `正式追蹤` tab must use only `tracking.formal_forward_records`.
- Only active formal rows count: `持有中` / `已出場` plus the defensive English aliases already supported by the helper.
- `待次日開盤` and `次日開盤未達進場條件` must be excluded from the new formal stock list.
- The existing `歷史交易` list behavior must remain unchanged.
- Tests must follow TDD: write failing tests first, verify RED, then implement minimal code for GREEN.

---

### Task 1: Add Formal-Tracking Helper Coverage

**Files:**
- Modify: `C:\Users\Wei&Ting\Documents\Codex\2026-06-10\git-daily-stock-signal-etf-track-worktrees\mwp-c-formal-forward-display\tests\test_mwp_c_strategy_helpers.js`
- Modify: `C:\Users\Wei&Ting\Documents\Codex\2026-06-10\git-daily-stock-signal-etf-track-worktrees\mwp-c-formal-forward-display\mwp_c_strategy_helpers.js`

**Interfaces:**
- Consumes: `isActiveForwardStatus(status)`
- Produces: `buildFormalForwardGroups(records)` returning grouped stock cards with normalized trade rows

- [ ] **Step 1: Write the failing test**

```javascript
test("buildFormalForwardGroups keeps only active rows and sorts holdings first", () => {
  const groups = buildFormalForwardGroups([
    { id: "pending", market: "TWSE", stock_no: "1111", stock_name: "甲", status: "待次日開盤", signal_date: "2026-07-03" },
    { id: "hold", market: "TWSE", stock_no: "2330", stock_name: "台積電", status: "持有中", signal_date: "2026-06-29", entry_date: "2026-06-30", entry_price: 100, latest_close_date: "2026-07-02", latest_close: 110, unrealized_return_pct: 10, holding_days: 2, unit_type: "base" },
    { id: "exit", market: "TWSE", stock_no: "2882", stock_name: "國泰金", status: "已出場", signal_date: "2026-06-20", entry_date: "2026-06-21", entry_price: 50, exit_date: "2026-06-28", exit_price: 53, return_pct: 6, holding_days: 5, unit_type: "base" },
    { id: "fail", market: "TWSE", stock_no: "2222", stock_name: "乙", status: "次日開盤未達進場條件", signal_date: "2026-07-03" },
  ]);

  assert.deepEqual(groups.map((group) => group.stockNo), ["2330", "2882"]);
  assert.equal(groups[0].trades[0].statusLabel, "持有中");
  assert.equal(groups[1].trades[0].statusLabel, "已出場");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: FAIL because `buildFormalForwardGroups` is not exported yet.

- [ ] **Step 3: Write minimal implementation**

```javascript
function buildFormalForwardGroups(records) {
  const map = new Map();
  [...(records || [])]
    .filter((row) => isActiveForwardStatus(row?.status))
    .forEach((row, index) => {
      const market = String(row?.market || "").toUpperCase();
      const stockNo = String(row?.stock_no || "");
      if (!market || !stockNo) return;
      const key = `${market}:${stockNo}`;
      const unresolved = !hasExitDate(row);
      const trade = {
        id: row?.id || `${key}:${index}`,
        market,
        stockNo,
        stockName: row?.stock_name || "",
        label: row?.label || `${stockNo} ${row?.stock_name || ""}`.trim(),
        entryDate: row?.entry_date || "",
        entryPrice: toNumber(row?.entry_price),
        exitDate: unresolved ? row?.latest_close_date || "" : row?.exit_date || "",
        exitPrice: unresolved ? toNumber(row?.latest_close) : toNumber(row?.exit_price),
        signalDate: row?.signal_date || "",
        returnPct: unresolved ? toNumber(row?.unrealized_return_pct) : toNumber(row?.return_pct),
        pnl: estimatePnlFromReturnPct(unresolved ? row?.unrealized_return_pct : row?.return_pct),
        unitType: row?.unit_type || "base",
        addonNumber: row?.addon_number || 0,
        exitReason: unresolved ? "latest_close" : row?.exit_reason || "",
        holdingDays: row?.holding_days,
        unresolved,
        status: unresolved ? "unrealized" : "realized",
        statusLabel: unresolved ? "持有中" : "已出場",
      };
      if (!map.has(key)) map.set(key, { key, market, stockNo, stockName: trade.stockName, label: trade.label, trades: [] });
      map.get(key).trades.push(trade);
    });
  return [...map.values()];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_mwp_c_strategy_helpers.js mwp_c_strategy_helpers.js
git commit -m "Add formal forward stock grouping helper"
```

### Task 2: Add The Left-Panel View Switch On The Realized PnL Page

**Files:**
- Modify: `C:\Users\Wei&Ting\Documents\Codex\2026-06-10\git-daily-stock-signal-etf-track-worktrees\mwp-c-formal-forward-display\tests\test_verify_mwp_c_realized_pnl_labels.py`
- Modify: `C:\Users\Wei&Ting\Documents\Codex\2026-06-10\git-daily-stock-signal-etf-track-worktrees\mwp-c-formal-forward-display\mwp_c_realized_pnl.html`

**Interfaces:**
- Consumes: `window.mwpCStrategyHelpers.buildFormalForwardGroups(records)`
- Produces: new `歷史交易 / 正式追蹤` tabbed stock-list UI on the realized-PnL page

- [ ] **Step 1: Write the failing UI contract test**

```python
def test_page_contains_formal_tracking_view_switch(self) -> None:
    self.assertIn("歷史交易", self.html)
    self.assertIn("正式追蹤", self.html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_verify_mwp_c_realized_pnl_labels -v`
Expected: FAIL because the page does not expose both tab labels yet.

- [ ] **Step 3: Write minimal implementation**

```html
<div class="view-switch" role="tablist" aria-label="股票交易清單視圖">
  <button class="mode-button" id="historyViewButton" type="button" data-view="historical">歷史交易</button>
  <button class="mode-button" id="formalViewButton" type="button" data-view="formal">正式追蹤</button>
</div>
```

```javascript
state.activeView = "historical";
state.historicalGroups = groupRealizedTrades(rows);
state.formalGroups = window.mwpCStrategyHelpers.buildFormalForwardGroups(
  payload.tracking?.formal_forward_records || []
);
```

```javascript
function currentGroups() {
  return state.activeView === "formal" ? state.formalGroups : state.historicalGroups;
}
```

- [ ] **Step 4: Run tests and build**

Run: `python -m unittest tests.test_verify_mwp_c_realized_pnl_labels -v`
Expected: PASS

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: PASS

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File build_site.ps1`
Expected: site build succeeds

- [ ] **Step 5: Commit**

```bash
git add tests/test_verify_mwp_c_realized_pnl_labels.py mwp_c_realized_pnl.html
git commit -m "Add formal tracking stock list view on realized pnl page"
```

### Task 3: Full Verification, Deploy, And Live Check

**Files:**
- Verify only

**Interfaces:**
- Consumes: Task 1 helper and Task 2 page integration
- Produces: fresh evidence that the feature is built, deployed, and visible

- [ ] **Step 1: Run the focused Python page test**

Run: `python -m unittest tests.test_verify_mwp_c_realized_pnl_labels -v`
Expected: PASS

- [ ] **Step 2: Run the helper test suite**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: PASS

- [ ] **Step 3: Run the site build**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File build_site.ps1`
Expected: `Built static site at ...\site`

- [ ] **Step 4: Run diff hygiene**

Run: `git diff --check`
Expected: no patch-format errors beyond any pre-existing CRLF warnings

- [ ] **Step 5: Deploy and verify live**

Run: `git push origin HEAD:main`
Expected: push succeeds and triggers deploy

Run: `curl.exe -L https://daily-stock-signal.pages.dev/mwp_c_realized_pnl.html`
Expected: the deployed HTML contains `正式追蹤` and the new left-panel view-switch wiring
