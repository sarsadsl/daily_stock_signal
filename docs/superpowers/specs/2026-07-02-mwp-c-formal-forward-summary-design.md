# MWP-C Formal Forward Summary Design

## Goal

Add a `正式追蹤專屬` summary section to `mwp_c_realized_pnl.html` so the page can show the real forward performance of the formal tracking cohort without mixing it with the older historical backtest units.

## Problem

`mwp_c_realized_pnl.html` currently summarizes:

- `tracking.historical_realized_units`
- `tracking.historical_unresolved_units`

Those datasets cover the broader historical strategy record and are not the same cohort as the recently added `tracking.formal_forward_records`. As a result, the page cannot answer the user's question: "After we started formal tracking, how is the real realized/unrealized performance doing?"

## Approved Scope

Add a new summary area that uses only `tracking.formal_forward_records` and counts only active formal forward rows:

- include rows that are currently "holding" or "exited"
- exclude rows that are still pending next-day open
- exclude rows that failed the next-day entry filter

This new summary must not replace or rewrite the existing realized/unrealized stock-group list. It is an additional forward-only performance view.

## Data Definition

The formal forward summary is based on `tracking.formal_forward_records`.

Included rows:

- rows for which `mwp_c_strategy_helpers.isActiveForwardStatus(status)` returns true

Excluded rows:

- pending rows
- failed-entry rows

Derived buckets:

- realized forward rows: included rows with `exit_date`
- unrealized forward rows: included rows without `exit_date`

Metric rules:

- forward total count: all included rows
- forward realized count: rows with `exit_date`
- forward unrealized count: rows without `exit_date`
- forward realized win rate: realized rows with non-negative return divided by realized count
- forward realized average return: arithmetic mean of realized-row `return_pct`
- forward realized total pnl: sum of realized-row `pnl`
- forward unrealized pnl: sum of unrealized-row `pnl`

If a value is missing, treat it as zero only for additive PnL math; count-based and average metrics should only use the rows that are actually in the relevant bucket.

## UX

`mwp_c_realized_pnl.html` gets one extra summary band near the top, visually distinct but aligned with the existing metric cards.

The section should make it obvious that this is:

- formal tracking only
- forward real-world cohort only
- not the same as the broader historical strategy summary already on the page

Suggested visible labels:

- 正式追蹤總筆數
- 正式追蹤已出場
- 正式追蹤持有中
- 正式追蹤已出場勝率
- 正式追蹤已出場平均報酬
- 正式追蹤已出場總損益
- 正式追蹤持有中未實現損益

The final layout can combine some labels into four cards if that fits the page better, as long as the distinction between realized and unrealized forward metrics stays clear.

## Code Design

Extend `mwp_c_strategy_helpers.js` with a reusable summary builder for formal forward records.

New helper responsibility:

- accept raw `formal_forward_records`
- reuse the existing active-status logic
- return a normalized summary object for the forward-only metrics

This keeps the formal-forward semantics in one place and avoids duplicating the status interpretation across multiple pages.

`mwp_c_realized_pnl.html` should:

- load `mwp_c_strategy_helpers.js`
- call the new helper from `loadData()`
- render the new summary from the returned object

## Testing

Add helper-level tests in `tests/test_mwp_c_strategy_helpers.js`.

Required coverage:

- pending and failed-entry rows are excluded from the formal forward summary
- exited rows contribute to realized metrics
- holding rows contribute to unrealized metrics
- realized win rate / average return / realized total pnl are calculated from exited rows only

No new browser-only test harness is needed for this change; helper coverage plus the existing site build is sufficient.

## Non-Goals

- do not rewrite the existing stock-group list in `mwp_c_realized_pnl.html`
- do not relabel older historical backtest units as formal forward units
- do not change `formal_forward_records` generation in Python
- do not merge the historical and formal-forward summaries into one blended metric set
