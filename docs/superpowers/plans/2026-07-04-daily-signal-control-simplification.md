# Daily Signal Control Simplification Plan

1. Add regression tests that fail while the old search/market/upload/reset controls and `<a>` topbar links still exist.
2. Update `signal_dashboard.html`:
   - remove the requested controls
   - simplify filter state and listeners
   - convert report links to buttons
3. Update `mwp_c_strategy.html` and `mwp_c_realized_pnl.html` to use button-based topbar navigation.
4. Run targeted tests, full test discovery, and static site build.
5. Review the resulting diff and deployment readiness.
