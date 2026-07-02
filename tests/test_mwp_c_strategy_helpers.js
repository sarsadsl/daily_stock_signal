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

test("visible count semantics drop pending rows", () => {
  const rows = [
    { id: "active-hold", status: "持有中", signal_date: "2026-06-29" },
    { id: "today-fail", status: "次日開盤未達進場條件", signal_date: "2026-07-01" },
    { id: "pending", status: "待次日開盤", signal_date: "2026-07-01" },
  ];

  const visible = buildVisibleForwardRecords(rows, "2026-07-01");

  assert.equal(visible.length, 2);
});
