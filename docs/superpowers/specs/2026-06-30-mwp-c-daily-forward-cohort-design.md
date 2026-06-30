# MWP-C Daily Forward Cohort Automation Design

## Objective

Make the existing weekday GitHub Actions job update the MWP-C formal forward
cohort immediately after daily market data and signal reports are refreshed.
No manual local rebuild should be required.

## Data Flow

1. `sync_today.py` refreshes TWSE and TPEX market CSV files.
2. `alert_signals.py` generates the daily signal reports.
3. The existing freshness check confirms the report date.
4. `build_mwp_a_strategy_tracking.py` scans the latest market date, appends new
   mother/add-on candidates to the append-only forward record file, and updates
   existing records using only newly available market data.
5. `verify_mwp_c_forward_records.py` confirms that the radar date matches the
   daily report date and that every current mother/add-on candidate has a
   corresponding locked forward record.
6. `build_site.ps1` publishes the refreshed tracking payload.
7. The daily bot commits both MWP-C tracking JSON files with the market data.

## Integrity Rules

- Existing forward record IDs must not be rewritten or removed.
- Mother IDs use `{market}:{stock_no}:{signal_date}:base`.
- Add-on IDs use
  `{market}:{stock_no}:{mother_signal_date}:addon:{addon_number}`.
- A workflow run fails before deployment and push if the tracking date is stale,
  a candidate is absent from the formal cohort, or duplicate forward IDs exist.
- `reports/mwp_c_forward_records.json` is force-added because generated reports
  are ignored by the repository-wide `reports/` rule.

## Verification

- Unit tests cover complete cohorts, missing candidate IDs, duplicate IDs, and
  date mismatches.
- The verifier is run against the rebased `2026-06-29` data.
- Python compilation, unit tests, MWP-C tracker generation, site build, and Git
  diff checks must pass before commit and push.
