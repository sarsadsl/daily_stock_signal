# MWP-C Realized PnL Formal Stock List Design

## Goal

Add a dedicated `正式追蹤` stock-trade list to `mwp_c_realized_pnl.html` so the user can inspect the formal tracking pool in the same page and K-line workflow as the existing historical realized/unrealized list.

## Problem

`mwp_c_realized_pnl.html` already has a top-level formal-forward summary, but the left-side `股票交易清單` still only shows the older historical realized/unrealized units. That means the page can answer "formal tracking overall summary" but cannot answer "which formal-tracking stocks are currently held or already exited, and what do their realized / unrealized trade rows look like?"

## Approved UX

Keep the current page structure and K-line chart area. Inside the left stock-list panel:

- keep the panel title `股票交易清單`
- add a two-state view switch: `歷史交易` and `正式追蹤`
- keep one shared search box under the switch
- filter only the currently active view
- reuse the same expand/collapse group cards and the same right-side K-line chart

This is the approved option `1` from the earlier discussion.

## Formal-Tracking Data Rules

The new `正式追蹤` list must use only `tracking.formal_forward_records`.

Included rows:

- `持有中`
- `已出場`
- defensive English aliases already recognized by `mwp_c_strategy_helpers.js` (`open`, `exited`)

Excluded rows:

- `待次日開盤`
- `次日開盤未達進場條件`

Reason: pending and failed-entry rows often do not have `entry_date`, `entry_price`, `exit_date`, or `return_pct`, so they do not fit the realized-PnL page's trade-row interaction and should stay on the formal-tracking strategy page rather than this page.

## Grouping Rules

Group formal-tracking rows by `market + stock_no`, matching the current historical-list grouping pattern.

Per trade row, preserve the same basic shape as the historical list:

- status chip
- unit label (`母單` / `加碼單 #n`)
- entry line
- exit or latest-close line
- holding days
- realized or unrealized PnL

Per stock group, show:

- stock label
- market label
- latest formal event date
- realized / unrealized count
- realized / unrealized PnL subtotals

## Shared Semantics

The page already uses `mwp_c_strategy_helpers.js` for formal-forward summary logic. Extend that shared helper with one reusable grouping builder for formal-tracking rows instead of duplicating lifecycle interpretation inside `mwp_c_realized_pnl.html`.

The helper should:

- filter to active formal rows only
- normalize row fields into UI-ready trade objects
- group rows by `market + stock_no`
- sort groups so active holdings appear first
- sort trade rows newest-first within each stock

## Sorting

Formal-tracking stock groups should prioritize current holdings.

Recommended order:

1. groups with at least one `持有中` row
2. groups with no holding rows but with `已出場` rows
3. within the same bucket, newer event dates first
4. then larger total PnL first as a stable tie-breaker

This keeps the user's active official-tracking stocks at the top of the list.

## Testing

Required coverage:

- helper test proving pending and failed-entry rows are excluded from the formal stock list
- helper test proving holdings sort ahead of exited-only groups
- helper test proving trade rows are normalized for the existing trade-row renderer
- page-level label test proving `歷史交易` and `正式追蹤` are present on `mwp_c_realized_pnl.html`

## Non-Goals

- do not change the existing historical trade list semantics
- do not merge historical and formal rows into one blended dataset
- do not change Python generation of `formal_forward_records`
- do not move pending / failed-entry observation rows from the strategy page onto the realized PnL page
