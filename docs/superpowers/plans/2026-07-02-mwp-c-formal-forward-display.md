# MWP-C Formal Forward Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the `正式追蹤` table so active lifecycle rows render first, and failed-entry rows only render for the current signal day.

**Architecture:** Keep `formal_forward_records` unchanged and move display-only filtering/sorting into a small browser helper module consumed by `mwp_c_strategy.html`. Test the helper directly with Node so the page and test share the same logic.

**Tech Stack:** Static HTML, plain JavaScript, Node.js, Python unittest suite already present in repo

## Global Constraints

- Do not change `build_mwp_a_strategy_tracking.py` payload semantics for this feature.
- Treat entered lifecycle display states as a single bucket for ordering purposes.
- Only keep `次日開盤未達進場條件` rows when `signal_date === as_of_daily_signal_date`.
- Keep verification lightweight and reproducible from the clean worktree.

---

### Task 1: Extract Forward Display Logic Into a Testable Helper

**Files:**
- Create: `mwp_c_strategy_helpers.js`
- Create: `tests/test_mwp_c_strategy_helpers.js`

**Interfaces:**
- Consumes: raw `formal_forward_records` rows and `as_of_daily_signal_date`
- Produces: `buildVisibleForwardRecords(records, asOfDate)` and `isActiveForwardStatus(status)`

- [ ] **Step 1: Write the failing test**

```javascript
const test = require("node:test");
const assert = require("node:assert/strict");
const {
  buildVisibleForwardRecords,
  isActiveForwardStatus,
} = require("../mwp_c_strategy_helpers.js");

test("active statuses are treated as primary rows", () => {
  assert.equal(isActiveForwardStatus("持有中"), true);
  assert.equal(isActiveForwardStatus("已出場"), true);
  assert.equal(isActiveForwardStatus("待次日開盤"), false);
});

test("buildVisibleForwardRecords keeps active rows first and only today's failed entries", () => {
  const rows = [
    { id: "old-fail", status: "次日開盤未達進場條件", signal_date: "2026-06-25" },
    { id: "active-hold", status: "持有中", signal_date: "2026-06-29", entry_date: "2026-06-30" },
    { id: "today-fail", status: "次日開盤未達進場條件", signal_date: "2026-07-01" },
    { id: "active-exit", status: "已出場", signal_date: "2026-06-20", entry_date: "2026-06-21" },
    { id: "pending", status: "待次日開盤", signal_date: "2026-07-01" },
  ];

  const visible = buildVisibleForwardRecords(rows, "2026-07-01");

  assert.deepEqual(
    visible.map((row) => row.id),
    ["active-hold", "active-exit", "today-fail"]
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: FAIL because `mwp_c_strategy_helpers.js` does not exist yet

- [ ] **Step 3: Write minimal implementation**

```javascript
(function initForwardHelpers(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.mwpCStrategyHelpers = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function factory() {
  const ACTIVE_FORWARD_STATUSES = new Set(["持有中", "已出場", "已進場", "open", "exited"]);
  const FAILED_ENTRY_STATUSES = new Set(["次日開盤未達進場條件", "entry_filter_failed"]);

  function compareDesc(left, right) {
    return String(right || "").localeCompare(String(left || ""));
  }

  function isActiveForwardStatus(status) {
    return ACTIVE_FORWARD_STATUSES.has(String(status || ""));
  }

  function isFailedForwardStatus(status) {
    return FAILED_ENTRY_STATUSES.has(String(status || ""));
  }

  function buildVisibleForwardRecords(records, asOfDate) {
    return [...(records || [])]
      .filter((row) => {
        if (isActiveForwardStatus(row?.status)) return true;
        return isFailedForwardStatus(row?.status) && String(row?.signal_date || "") === String(asOfDate || "");
      })
      .sort((left, right) => {
        const leftRank = isActiveForwardStatus(left?.status) ? 0 : 1;
        const rightRank = isActiveForwardStatus(right?.status) ? 0 : 1;
        if (leftRank !== rightRank) return leftRank - rightRank;
        return (
          compareDesc(left?.signal_date, right?.signal_date) ||
          compareDesc(left?.entry_date, right?.entry_date) ||
          compareDesc(left?.id, right?.id) ||
          compareDesc(left?.label, right?.label)
        );
      });
  }

  return { buildVisibleForwardRecords, isActiveForwardStatus };
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mwp_c_strategy_helpers.js tests/test_mwp_c_strategy_helpers.js
git commit -m "test: add MWP-C forward display helper coverage"
```

### Task 2: Wire the Helper Into the MWP-C Strategy Page

**Files:**
- Modify: `mwp_c_strategy.html`
- Test: `tests/test_mwp_c_strategy_helpers.js`

**Interfaces:**
- Consumes: `window.mwpCStrategyHelpers.buildVisibleForwardRecords(records, asOfDate)`
- Produces: filtered and reordered rows in the `正式追蹤` table plus a count matching visible rows

- [ ] **Step 1: Write the failing integration test**

```javascript
test("helper output supports the page's visible count semantics", () => {
  const rows = [
    { id: "active-hold", status: "持有中", signal_date: "2026-06-29" },
    { id: "today-fail", status: "次日開盤未達進場條件", signal_date: "2026-07-01" },
    { id: "pending", status: "待次日開盤", signal_date: "2026-07-01" },
  ];

  const visible = buildVisibleForwardRecords(rows, "2026-07-01");

  assert.equal(visible.length, 2);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: FAIL until helper filtering is strict enough to drop `待次日開盤`

- [ ] **Step 3: Write minimal implementation**

```html
<script src="mwp_c_strategy_helpers.js"></script>
```

```javascript
function renderForward(records, note, asOfDate) {
  const visible = window.mwpCStrategyHelpers
    ? window.mwpCStrategyHelpers.buildVisibleForwardRecords(records, asOfDate)
    : (records || []);
  document.getElementById("forwardCount").textContent = `${visible.length} 筆`;
  document.getElementById("forwardNote").textContent = note || "正式追蹤 forward records";
  document.getElementById("forwardRows").innerHTML = visible.map(/* existing row template */).join("") || /* existing empty row */;
}
```

And update the call site:

```javascript
renderForward(
  tracking.formal_forward_records || [],
  tracking.formal_forward_note,
  tracking.as_of_daily_signal_date
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/test_mwp_c_strategy_helpers.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mwp_c_strategy.html
git commit -m "feat: reorder visible MWP-C formal forward records"
```

### Task 3: Verify Against Latest Remote-Semantics Data

**Files:**
- Modify: `CODEX_HANDOFF.md`
- Test: `tests/test_mwp_c_strategy_helpers.js`

**Interfaces:**
- Consumes: current worktree `reports/mwp_a_strategy_tracking.json`
- Produces: verified behavior summary for `3008` and `2882` style active records and current-day failed-entry filtering

- [ ] **Step 1: Write the verification command set**

```bash
node tests/test_mwp_c_strategy_helpers.js
python -m unittest discover -s tests -v
```

- [ ] **Step 2: Run verification**

Run the commands above and inspect output for zero failures.

- [ ] **Step 3: Perform a targeted data sanity check**

```bash
python - <<'PY'
import json
from pathlib import Path
data = json.loads(Path("reports/mwp_a_strategy_tracking.json").read_text(encoding="utf-8"))
records = data["tracking"]["formal_forward_records"]
rows = [r for r in records if str(r.get("stock_no")) in {"3008", "2882"}]
for row in rows:
    print(row["id"], row["status"], row.get("entry_date"), row.get("entry_price"))
PY
```

Expected: `2026-06-29` base rows for `3008` and `2882` show active holding semantics from latest data.

- [ ] **Step 4: Update handoff**

Record the worktree path, the remote-based semantics, files changed, and verification results in `CODEX_HANDOFF.md`.

- [ ] **Step 5: Commit**

```bash
git add CODEX_HANDOFF.md
git commit -m "docs: update handoff for MWP-C forward display"
```
