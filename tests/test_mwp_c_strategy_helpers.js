const test = require("node:test");
const assert = require("node:assert/strict");
const {
  buildVisibleForwardRecords,
  buildFormalForwardSummary,
  isActiveForwardStatus,
} = require("../mwp_c_strategy_helpers.js");

test("active statuses are treated as primary rows", () => {
  assert.equal(isActiveForwardStatus("open"), true);
  assert.equal(isActiveForwardStatus("exited"), true);
  assert.equal(isActiveForwardStatus("pending"), false);
});

test("buildVisibleForwardRecords keeps active rows first and only today's failed entries", () => {
  const rows = [
    { id: "old-fail", status: "entry_filter_failed", signal_date: "2026-06-25" },
    { id: "active-hold", status: "open", signal_date: "2026-06-29", entry_date: "2026-06-30" },
    { id: "today-fail", status: "entry_filter_failed", signal_date: "2026-07-01" },
    { id: "active-exit", status: "exited", signal_date: "2026-06-20", entry_date: "2026-06-21" },
    { id: "pending", status: "pending", signal_date: "2026-07-01" },
  ];

  const visible = buildVisibleForwardRecords(rows, "2026-07-01");

  assert.deepEqual(
    visible.map((row) => row.id),
    ["active-hold", "active-exit", "today-fail"]
  );
});

test("visible count semantics drop pending rows", () => {
  const rows = [
    { id: "active-hold", status: "open", signal_date: "2026-06-29" },
    { id: "today-fail", status: "entry_filter_failed", signal_date: "2026-07-01" },
    { id: "pending", status: "pending", signal_date: "2026-07-01" },
  ];

  const visible = buildVisibleForwardRecords(rows, "2026-07-01");

  assert.equal(visible.length, 2);
});

test("buildFormalForwardSummary derives forward metrics from realized and unrealized returns", () => {
  const summary = buildFormalForwardSummary([
    { status: "open", unrealized_return_pct: 12, exit_date: "" },
    { status: "exited", return_pct: 5, exit_date: "2026-07-01" },
    { status: "exited", return_pct: -3, exit_date: "2026-07-02" },
    { status: "entry_filter_failed", unrealized_return_pct: 99, exit_date: "" },
    { status: "pending", unrealized_return_pct: 99, exit_date: "" },
  ]);

  assert.deepEqual(summary, {
    totalCount: 3,
    realizedCount: 2,
    unrealizedCount: 1,
    realizedWinRate: 50,
    realizedAverageReturnPct: 1,
    realizedTotalPnl: 2000,
    unrealizedAverageReturnPct: 12,
    unrealizedTotalPnl: 12000,
  });
});
