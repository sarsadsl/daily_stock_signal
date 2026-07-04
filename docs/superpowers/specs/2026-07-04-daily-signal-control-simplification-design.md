# Daily Signal Control Simplification Design

## Objective

Simplify the top control bars so the pages remain usable on mobile and desktop, while preserving the core flows the user still needs.

## Approved Scope

- Remove these controls from `signal_dashboard.html` on both mobile and desktop:
  - search input
  - market selector
  - upload JSON control
  - clear/reset `X` button
- Keep the existing signal filter (`reasonFilter`) unless the user later asks to remove it.
- Convert topbar/report navigation from hyperlinks to real buttons on:
  - `signal_dashboard.html`
  - `mwp_c_strategy.html`
  - `mwp_c_realized_pnl.html`

## Implementation Notes

- Use semantic `<button type="button">` elements with `data-nav-url` and optional `data-nav-external="true"` markers.
- Add small shared inline navigation helpers per page instead of keeping mixed `<a>` / `<button>` markup.
- Remove dead JS wiring tied only to the deleted controls:
  - `searchInput`
  - `marketFilter`
  - `resetButton`
  - `fileInput`
- Simplify filter state on `signal_dashboard.html` so it only tracks the filters still exposed in the UI.

## Verification

- Add HTML-structure regression tests for removed controls and buttonized navigation.
- Run targeted tests, full test discovery, and `build_site.ps1`.
