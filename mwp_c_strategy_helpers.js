(function initForwardHelpers(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.mwpCStrategyHelpers = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function factory() {
  const NOTIONAL_CAPITAL_PER_UNIT = 100000;
  const HOLDING_FORWARD_STATUSES = new Set(["\u6301\u6709\u4e2d", "\u5df2\u9032\u5834", "open"]);
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

  function estimateLatestPrice(entryPrice, returnPct) {
    const base = toNumber(entryPrice);
    if (!base) {
      return null;
    }
    return base * (1 + toNumber(returnPct) / 100);
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

  function buildFormalForwardGroups(records, asOfDate) {
    const groups = new Map();

    [...(records || [])]
      .filter((row) => isActiveForwardStatus(row?.status))
      .forEach((row, index) => {
        const market = String(row?.market || "").toUpperCase();
        const stockNo = String(row?.stock_no || "");
        if (!market || !stockNo) {
          return;
        }

        const key = `${market}:${stockNo}`;
        const unresolved = !hasExitDate(row);
        const returnPct = unresolved
          ? toNumber(row?.unrealized_return_pct)
          : toNumber(row?.return_pct);
        const trade = {
          ...row,
          id:
            row?.id ||
            `${key}:${unresolved ? "holding" : "exited"}:${
              row?.unit_type || "base"
            }:${index}`,
          key,
          market,
          stockNo,
          stockName: row?.stock_name || "",
          label: row?.label || `${stockNo} ${row?.stock_name || ""}`.trim(),
          entryDate: row?.entry_date || "",
          entryPrice: toNumber(row?.entry_price),
          exitDate: unresolved
            ? String(row?.latest_close_date || asOfDate || "")
            : String(row?.exit_date || ""),
          exitPrice: unresolved
            ? toNumber(row?.latest_close) ||
              estimateLatestPrice(row?.entry_price, row?.unrealized_return_pct)
            : toNumber(row?.exit_price),
          signalDate: row?.signal_date || "",
          returnPct,
          pnl: estimatePnlFromReturnPct(returnPct),
          unitType: row?.unit_type || "base",
          addonNumber: row?.addon_number || 0,
          exitReason: unresolved ? "latest_close" : row?.exit_reason || "",
          holdingDays: row?.holding_days ?? null,
          unresolved,
          status: unresolved ? "unrealized" : "realized",
          statusLabel: unresolved ? "持有中" : "已出場",
        };

        if (!groups.has(key)) {
          groups.set(key, {
            key,
            market,
            stockNo,
            stockName: trade.stockName,
            label: trade.label,
            trades: [],
          });
        }
        groups.get(key).trades.push(trade);
      });

    return [...groups.values()]
      .map((group) => {
        group.trades.sort((left, right) => {
          const leftRank = left.unresolved ? 0 : 1;
          const rightRank = right.unresolved ? 0 : 1;
          if (leftRank !== rightRank) {
            return leftRank - rightRank;
          }
          return (
            compareDesc(left?.exitDate, right?.exitDate) ||
            compareDesc(left?.entryDate, right?.entryDate) ||
            compareDesc(left?.id, right?.id)
          );
        });

        const realizedTrades = group.trades.filter((trade) => !trade.unresolved);
        const unrealizedTrades = group.trades.filter((trade) => trade.unresolved);
        const realizedPnl = realizedTrades.reduce((sum, trade) => sum + trade.pnl, 0);
        const unrealizedPnl = unrealizedTrades.reduce(
          (sum, trade) => sum + trade.pnl,
          0
        );
        const totalPnl = realizedPnl + unrealizedPnl;
        const realizedReturns = realizedTrades
          .map((trade) => trade.returnPct)
          .sort((left, right) => left - right);
        const wins = realizedTrades.filter((trade) => trade.pnl >= 0).length;
        const losses = realizedTrades.length - wins;
        const mid = Math.floor(realizedReturns.length / 2);
        const eventDates = group.trades
          .flatMap((trade) => [trade.exitDate, trade.entryDate, trade.signalDate])
          .filter(Boolean)
          .sort();

        return {
          ...group,
          realizedPnl,
          unrealizedPnl,
          totalPnl,
          realizedCount: realizedTrades.length,
          unrealizedCount: unrealizedTrades.length,
          wins,
          losses,
          winRate: realizedTrades.length
            ? (wins / realizedTrades.length) * 100
            : 0,
          avgReturn: realizedReturns.length
            ? realizedReturns.reduce((sum, value) => sum + value, 0) /
              realizedReturns.length
            : null,
          medianReturn: realizedReturns.length
            ? realizedReturns.length % 2
              ? realizedReturns[mid]
              : (realizedReturns[mid - 1] + realizedReturns[mid]) / 2
            : null,
          latestExit: eventDates.length ? eventDates[eventDates.length - 1] : "",
          holdingCount: unrealizedTrades.length,
        };
      })
      .sort(
        (left, right) =>
          right.holdingCount - left.holdingCount ||
          compareDesc(left?.latestExit, right?.latestExit) ||
          right.totalPnl - left.totalPnl ||
          compareDesc(left?.key, right?.key)
      );
  }

  return {
    buildFormalForwardGroups,
    buildFormalForwardSummary,
    buildVisibleForwardRecords,
    isActiveForwardStatus,
  };
});
