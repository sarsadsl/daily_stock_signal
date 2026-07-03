const test = require("node:test");
const assert = require("node:assert/strict");
const {
  buildVisibleForwardRecords,
  buildFormalForwardSummary,
  buildFormalForwardGroups,
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

test("buildFormalForwardGroups keeps only active rows and sorts holding stocks first", () => {
  const groups = buildFormalForwardGroups([
    {
      id: "pending",
      market: "TWSE",
      stock_no: "1111",
      stock_name: "甲公司",
      status: "待次日開盤",
      signal_date: "2026-07-03",
    },
    {
      id: "exited-base",
      market: "TWSE",
      stock_no: "2882",
      stock_name: "國泰金",
      label: "2882 國泰金",
      status: "已出場",
      signal_date: "2026-06-20",
      entry_date: "2026-06-21",
      entry_price: 50,
      exit_date: "2026-06-28",
      exit_price: 53,
      return_pct: 6,
      holding_days: 5,
      unit_type: "base",
    },
    {
      id: "holding-base",
      market: "TWSE",
      stock_no: "3008",
      stock_name: "大立光",
      label: "3008 大立光",
      status: "持有中",
      signal_date: "2026-06-29",
      entry_date: "2026-06-30",
      entry_price: 2200,
      latest_close_date: "2026-07-02",
      latest_close: 2310,
      unrealized_return_pct: 5,
      holding_days: 2,
      unit_type: "base",
    },
    {
      id: "failed-entry",
      market: "TWSE",
      stock_no: "2222",
      stock_name: "乙公司",
      status: "次日開盤未達進場條件",
      signal_date: "2026-07-03",
    },
  ]);

  assert.deepEqual(
    groups.map((group) => group.stockNo),
    ["3008", "2882"]
  );
  assert.equal(groups[0].trades[0].statusLabel, "持有中");
  assert.equal(groups[0].trades[0].unresolved, true);
  assert.equal(groups[0].trades[0].exitDate, "2026-07-02");
  assert.equal(groups[0].trades[0].exitPrice, 2310);
  assert.equal(groups[1].trades[0].statusLabel, "已出場");
  assert.equal(groups[1].trades[0].unresolved, false);
});
