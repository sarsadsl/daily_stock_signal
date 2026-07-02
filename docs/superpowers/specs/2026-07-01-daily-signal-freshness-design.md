# Daily Signal Freshness Verification Design

## Objective

Make the weekday daily-signal workflow fail with actionable diagnostics when the
latest synced market snapshot is stale or internally inconsistent, without
misclassifying a report-format artifact as the root cause.

## Current Failure

- The workflow currently reads only `reports/daily_signal_alert.csv` and treats
  an empty `date` column set as a stale deployment blocker.
- In GitHub Actions run `28517462823`, that produced
  `Stale report: expected 2026-07-01, got .` even though the more important
  question was whether the synced market inputs for `2026-07-01` were valid.
- The workflow leaves no counts for latest-date symbols, latest-date
  volume-qualified symbols, or latest-date signal matches, so transient upstream
  data issues cannot be diagnosed after the ephemeral runner is destroyed.

## Design

Add a dedicated verifier script, `verify_daily_signal_freshness.py`, and let the
workflow call it after `alert_signals.py`.

The verifier should:

1. Resolve the expected business date from `--expected-date` or the current
   `Asia/Taipei` weekday date.
2. Skip freshness enforcement on Taipei weekends, preserving the current
   workflow behavior.
3. Inspect raw market data through the existing `run_market_backtest` helpers,
   not through the generated report CSV alone.
4. Compute:
   - global latest market date
   - number of symbols on that latest date
   - number of latest-date symbols passing the `1,000,000` volume-share gate
   - number of latest-date symbols producing at least one strategy signal
5. Read `reports/daily_signal_alert.csv` only as a secondary cross-check,
   reporting the latest report date and row count when present.
6. Exit non-zero with clear messages when:
   - latest market date does not equal the expected date
   - no latest-date symbols exist
   - no latest-date volume-qualified symbols exist
   - no latest-date signals exist
7. Print structured human-readable diagnostics before failing so Actions logs
   preserve enough evidence for later triage.

## Integrity Rules

- The verifier must reuse the existing signal logic from `run_market_backtest`
  so the diagnostics match production behavior.
- The workflow should fail on zero latest-date signals because the user expects
  signals every trading day.
- The verifier must not require notification secrets.
- The verifier must remain safe for `workflow_dispatch` runs with an explicit
  `as_of` date.

## Testing

- Unit tests should cover:
  - stale latest market date failure
  - zero latest-date signal failure even when latest-date rows exist
  - successful verification with latest-date signals
  - workflow ordering still keeping freshness verification before the MWP-C
    forward-cohort update step
- Tests should use temporary CSV fixtures and patch
  `verify_daily_signal_freshness.csv_files`, `read_rows`, and `prepare` where
  needed so they stay fast and deterministic.

