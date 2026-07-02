(function initForwardHelpers(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.mwpCStrategyHelpers = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function factory() {
  const NOTIONAL_CAPITAL_PER_UNIT = 100000;
  const HOLDING_FORWARD_STATUSES = new Set(["\u6301\u6709\u4e2d", "open"]);
  const EXITED_FORWARD_STATUSES = new Set(["\u5df2\u51fa\u5834", "exited"]);
  const FAILED_ENTRY_STATUSES = new Set([
    "\u6b21\u65e5\u958b\u76e4\u672a\u9054\u9032\u5834\u689d\u4ef6",
    "entry_filter_failed",
  ]);

  function compareDesc(left, right) {
    return String(right || "").localeCompare(String(left || ""));
  }

  function toNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function isHoldingForwardStatus(status) {
    return HOLDING_FORWARD_STATUSES.has(String(status || ""));
  }

  function isExitedForwardStatus(status) {
    return EXITED_FORWARD_STATUSES.has(String(status || ""));
  }

  function isActiveForwardStatus(status) {
    return isHoldingForwardStatus(status) || isExitedForwardStatus(status);
  }

  function isFailedForwardStatus(status) {
    return FAILED_ENTRY_STATUSES.has(String(status || ""));
  }

  function hasExitDate(row) {
    return String(row?.exit_date || "").trim().length > 0;
  }

  function estimatePnlFromReturnPct(returnPct) {
    return (toNumber(returnPct) / 100) * NOTIONAL_CAPITAL_PER_UNIT;
  }

  function buildVisibleForwardRecords(records, asOfDate) {
    return [...(records || [])]
      .filter((row) => {
        if (isActiveForwardStatus(row?.status)) {
          return true;
        }
        return (
          isFailedForwardStatus(row?.status) &&
          String(row?.signal_date || "") === String(asOfDate || "")
        );
      })
      .sort((left, right) => {
        const leftRank = isActiveForwardStatus(left?.status) ? 0 : 1;
        const rightRank = isActiveForwardStatus(right?.status) ? 0 : 1;
        if (leftRank !== rightRank) {
          return leftRank - rightRank;
        }
        return (
          compareDesc(left?.signal_date, right?.signal_date) ||
          compareDesc(left?.entry_date, right?.entry_date) ||
          compareDesc(left?.id, right?.id) ||
          compareDesc(left?.label, right?.label)
        );
      });
  }

  function buildFormalForwardSummary(records) {
    const activeRows = [...(records || [])].filter((row) =>
      isActiveForwardStatus(row?.status)
    );
    const realizedRows = activeRows.filter((row) => hasExitDate(row));
    const unrealizedRows = activeRows.filter((row) => !hasExitDate(row));
    const realizedWins = realizedRows.filter((row) => toNumber(row?.return_pct) >= 0);
    const realizedAverageReturnPct = realizedRows.length
      ? realizedRows.reduce((sum, row) => sum + toNumber(row?.return_pct), 0) /
        realizedRows.length
      : null;
    const unrealizedAverageReturnPct = unrealizedRows.length
      ? unrealizedRows.reduce(
          (sum, row) => sum + toNumber(row?.unrealized_return_pct),
          0
        ) / unrealizedRows.length
      : null;

    return {
      totalCount: activeRows.length,
      realizedCount: realizedRows.length,
      unrealizedCount: unrealizedRows.length,
      realizedWinRate: realizedRows.length
        ? (realizedWins.length / realizedRows.length) * 100
        : null,
      realizedAverageReturnPct,
      unrealizedAverageReturnPct,
      realizedTotalPnl: realizedRows.reduce(
        (sum, row) => sum + estimatePnlFromReturnPct(row?.return_pct),
        0
      ),
      unrealizedTotalPnl: unrealizedRows.reduce(
        (sum, row) =>
          sum + estimatePnlFromReturnPct(row?.unrealized_return_pct),
        0
      ),
    };
  }

  return {
    buildFormalForwardSummary,
    buildVisibleForwardRecords,
    isActiveForwardStatus,
  };
});
