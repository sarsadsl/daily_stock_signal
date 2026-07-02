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

  return {
    buildVisibleForwardRecords,
    isActiveForwardStatus,
  };
});
