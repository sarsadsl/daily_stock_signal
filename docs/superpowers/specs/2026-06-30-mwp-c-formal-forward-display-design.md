# MWP-C Formal Forward Display Design

## Objective

Adjust the `正式追蹤` table on `mwp_c_strategy.html` so the visible order and
filtering better match daily review needs, without changing the underlying
append-only `formal_forward_records` dataset.

## User-Approved Behavior

The user approved a frontend-only solution.

Visible ordering rules:

1. Records that have already entered the lifecycle should appear first.
2. `次日開盤未達進場條件` records should appear after those lifecycle records.
3. Among failed-entry records, only the records whose `signal_date` equals the
   current `as_of_daily_signal_date` should remain visible.

For this request, "have entered the lifecycle" means these statuses:

- `已進場`
- `持有中`
- `已出場`

Historical `次日開盤未達進場條件` rows from older signal dates should remain in
the raw payload but should not be rendered in the visible table.

## Scope

In scope:

- Update `renderForward(records, note)` in `mwp_c_strategy.html`
- Filter records only for display
- Reorder displayed rows only for display
- Keep the visible count aligned with the filtered row count

Out of scope:

- Changing `build_mwp_a_strategy_tracking.py` record generation
- Changing `mwp_c_forward_records.json` append-only semantics
- Changing other tables such as `今日雷達候選`

## Approach Options Considered

### Option 1: Frontend-only display transform

Filter and reorder `tracking.formal_forward_records` inside
`mwp_c_strategy.html` before rendering the `正式追蹤` rows.

Why this is the chosen option:

- Smallest change surface
- Lowest risk to formal tracking semantics
- Matches the user's request for a layout/display change

### Option 2: Add a display-specific payload in Python

Rejected for now because it mixes presentation rules into the tracking payload
without a current need from other pages.

### Option 3: Reorder the raw forward record list at sync time

Rejected because it would blur the distinction between persisted tracking facts
and one page's display preference.

## Detailed Design

`renderForward(records, note)` will:

1. Receive the raw `formal_forward_records`
2. Build a filtered display list
3. Render the filtered display list instead of the raw list

Filtering logic:

- Keep all rows whose normalized top-level status is not
  `entry_filter_failed`
- Keep `entry_filter_failed` rows only when `row.signal_date === current
  as_of_daily_signal_date`

Ordering logic:

- Group A: rows with statuses representing entered lifecycle records
- Group B: visible `entry_filter_failed` rows for the current day
- Sort Group A before Group B
- Within each group, prefer newer `signal_date` first
- Use stable secondary fields like `entry_date` and `id` or `label` to keep the
  table deterministic

Count behavior:

- `forwardCount` should show the filtered display count so the table and badge
  stay consistent

## Data and Interface Notes

No API contract changes are required. The page already has both:

- `tracking.formal_forward_records`
- `tracking.as_of_daily_signal_date`

That is sufficient for the display transform.

## Risks

- Status text on this page is normalized from stored values, so the display
  filter should rely on the same normalized top-level status values already used
  by `statusLabel`
- If a row uses `open` semantics for an entered trade but keeps a different raw
  localized string, the filter must use the normalized machine status key rather
  than only the displayed Traditional Chinese label

## Verification Plan

1. Run targeted tests or checks for the updated display helper logic
2. Rebuild or reload the generated page data if needed
3. Confirm the rendered `正式追蹤` table shows:
   - entered lifecycle records first
   - only today's failed-entry rows after them
   - no older failed-entry rows
4. Confirm the count badge matches the visible rows
