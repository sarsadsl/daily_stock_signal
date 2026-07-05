# MWP-C Open Entry Call Design

## Goal

Add a lightweight `open-entry call` flow for the existing MWP-C formal tracking cohort so the user can receive a Telegram alert as soon as the next trading day's open satisfies the existing official entry rule.

## User-Approved Semantics

The call flow must follow the current formal-tracking entry rule exactly.

- `D0`: a stock is already present in formal tracking as a pending next-open candidate
- `D1`: only the next trading day's open is checked
- trigger condition: `D1 open <= D0 close * 0.98`
- if the condition is satisfied, send a Telegram call immediately after the open is available
- if the condition is not satisfied at the open, do not continue watching intraday prices for that stock on `D1`

This feature does **not** introduce intraday chase entries. It is only an earlier notification layer for the same official formal-tracking rule.

## Non-Goals

- do not change the current formal-tracking entry rule
- do not introduce intraday low-based or 1-minute-K-based entries
- do not rename `reports/mwp_a_strategy_tracking.json` in this version
- do not create a new Telegram channel
- do not rewrite the `formal_forward_records` generation semantics

## Existing System Facts

Current formal tracking already records:

- `tracking.formal_forward_records`
- pending lifecycle rows such as `待次日開盤`
- `entry_limit_price`, which is the same official threshold used by the next-open entry gate

Current formal tracking writes `entry_price` as the next trading day's open when a record transitions into entry/hold semantics.

Therefore the new call flow should align with the existing data model instead of creating a second entry-price interpretation.

## Recommended Architecture

Implement a standalone script:

- `send_mwp_c_open_entry_calls.py`

Responsibilities:

1. Load `reports/mwp_a_strategy_tracking.json`
2. Read `tracking.formal_forward_records`
3. Filter to records that are still waiting for the next-open decision
4. For each eligible `D0` candidate, fetch the current `D1` daily open
5. Compare `D1 open` against `entry_limit_price`
6. Send Telegram call if the entry condition is satisfied
7. Persist a sent-log so the same `(market, stock_no, signal_date, unit_type, addon_number)` is not sent twice

This keeps the feature isolated from:

- the static-site build
- the dashboard UI
- the formal-tracking batch updater

## Data Inputs

Primary tracking input:

- `reports/mwp_a_strategy_tracking.json`

Candidate source:

- `tracking.formal_forward_records`

Required record fields:

- `market`
- `stock_no`
- `stock_name`
- `signal_date`
- `status`
- `entry_limit_price`
- `unit_type`
- `addon_number` when present

Open-price source:

- use the same market daily endpoints already used by `dashboard_server.py`
- TWSE daily payload
- TPEx daily payload

The script only needs the current day's first official `open` value, not intraday price history.

## Eligibility Rules

Eligible call candidates must satisfy all of the following:

- belong to `formal_forward_records`
- represent the next-open wait state, not already entered or exited
- correspond to `D1`, the trading day immediately after `signal_date`
- have a usable `entry_limit_price`
- have not already been sent in the sent-log

Ineligible rows:

- already entered / holding
- already exited
- failed-entry rows
- rows with missing threshold data
- rows whose `D1` has already passed and were previously processed

## Trigger Logic

For each eligible record:

1. Resolve the expected next trading date from the stock's price series
2. Confirm that today's market date is that `D1`
3. Fetch today's open
4. If open data is not yet available, exit cleanly without marking the record as failed
5. If `open <= entry_limit_price`, emit one Telegram call
6. If `open > entry_limit_price`, mark the record as checked for call purposes and do not keep watching intraday

The script must not trigger on:

- prior-day stale opens
- same-day repeated reruns
- later intraday lows after an opening failure

## Telegram Output

Use the existing alert transport already used by `alert_signals.py`.

The call message should include at minimum:

- strategy label: `MWP-C 正式追蹤開盤進場`
- stock code and name
- market
- `signal_date`
- `D0 close`
- `entry_limit_price`
- `D1 open`
- a clear statement that the stock has satisfied the official formal-tracking entry rule

Keep the message concise and aligned with the current Telegram alert style.

## Sent-Log

Add a small persistence file:

- `reports/mwp_c_open_entry_calls.json`

The log should track at least:

- stable record key
- market
- stock_no
- signal_date
- unit_type
- addon_number
- checked_date
- open_price
- entry_limit_price
- result: `called` or `open_failed`
- sent_at when applicable

Purpose:

- prevent duplicate Telegram sends
- preserve auditability of opening checks
- allow safe reruns during the same morning

## CLI Behavior

Recommended flags:

- `--as-of YYYY-MM-DD`
- `--dry-run`
- `--market twse,tpex`

Behavior:

- `--dry-run` prints would-send rows but does not send Telegram and does not persist final send state
- normal mode sends Telegram through the existing channel and writes the sent-log

## Failure Handling

If the script cannot fetch today's open for a candidate:

- do not misclassify it as failed entry
- do not send Telegram
- do not write a final `open_failed` result yet
- exit with a clear message that open data is not available

If the market endpoint is temporarily unavailable:

- fail the script clearly
- preserve current state so it can be rerun safely

## Testing

Required coverage:

- record is selected when status is next-open pending
- `open <= entry_limit_price` produces one call candidate
- `open > entry_limit_price` produces no call
- already-sent record is skipped
- missing open data does not produce a false failure
- `--dry-run` does not send or persist final call state

Recommended file additions:

- `tests/test_mwp_c_open_entry_calls.py`

## Rollout Plan

Phase 1:

- implement the standalone script
- verify with `--dry-run` against recent tracking data

Phase 2:

- enable real Telegram sends manually
- observe one or two live mornings before discussing automation

## Deferred Work

These are intentionally deferred until after the first working version:

- renaming `mwp_a_strategy_tracking.json`
- integrating the call log into dashboard UI
- adding scheduler / workflow automation
- extending the same logic to add-on next-open calls
