# MWP-C Daily Forward Cohort Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically append and validate MWP-C formal forward records during every successful weekday data refresh.

**Architecture:** Keep cohort generation in `build_mwp_a_strategy_tracking.py` and add a small standalone verifier that checks generated JSON invariants. Wire both commands into the existing daily workflow before the static-site build and include the generated tracking files in the bot commit.

**Tech Stack:** Python 3.12, `unittest`, GitHub Actions YAML, PowerShell site build.

## Global Constraints

- Preserve append-only forward record IDs and locked signal dates.
- Stop the workflow before deployment or push when cohort verification fails.
- Keep the existing single daily workflow to avoid concurrent writers.

---

### Task 1: Forward Cohort Verifier

**Files:**
- Create: `verify_mwp_c_forward_records.py`
- Create: `tests/test_verify_mwp_c_forward_records.py`

**Interfaces:**
- Consumes: daily signal CSV, MWP-C tracking JSON, and forward-record JSON paths.
- Produces: `verify_forward_records(expected_date, tracking, records)` and a CLI with exit code `0` only for a complete cohort.

- [ ] **Step 1: Write failing verifier tests**

Add tests that assert a complete cohort passes and missing IDs, duplicate IDs,
or mismatched dates raise `ValueError`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_verify_mwp_c_forward_records -v`

Expected: import failure because `verify_mwp_c_forward_records.py` does not exist.

- [ ] **Step 3: Implement the verifier**

Build expected mother and add-on IDs from
`tracking.daily_mwp_c_radar`, reject duplicates, compare dates, and expose a CLI
that derives the expected date from `reports/daily_signal_alert.csv` when
`--expected-date` is blank.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest tests.test_verify_mwp_c_forward_records -v`

Expected: all verifier tests pass.

### Task 2: Daily Workflow Integration

**Files:**
- Modify: `.github/workflows/daily-signal.yml`
- Modify: `CODEX_HANDOFF.md`

**Interfaces:**
- Consumes: the tracker and verifier commands from Task 1.
- Produces: refreshed and committed
  `reports/mwp_a_strategy_tracking.json` and
  `reports/mwp_c_forward_records.json` on every successful daily run.

- [ ] **Step 1: Add a failing static workflow assertion**

Extend the test module to assert that cohort generation and verification occur
after freshness verification and before `build_site.ps1`, and that both JSON
outputs appear in the generated-file commit list.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_verify_mwp_c_forward_records -v`

Expected: workflow integration assertion fails.

- [ ] **Step 3: Update the workflow**

Add an `Update and verify MWP-C forward cohort` step with:

```yaml
python build_mwp_a_strategy_tracking.py
python verify_mwp_c_forward_records.py --expected-date "${{ inputs.as_of }}"
```

Add both generated tracking JSON files to the bot's `files` array, where
`git add -f` already handles ignored generated files.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest tests.test_verify_mwp_c_forward_records -v`

Expected: all tests pass.

### Task 3: Regenerate, Verify, Commit, and Push

**Files:**
- Regenerate: `reports/mwp_a_strategy_tracking.json`
- Regenerate: `reports/mwp_c_forward_records.json`
- Regenerate: `site/`

**Interfaces:**
- Consumes: latest rebased market data and the completed workflow integration.
- Produces: a verified MWP-C strategy commit on remote `main`.

- [ ] **Step 1: Run complete verification**

Run Python compilation, unit tests, the tracker, the verifier, and
`build_site.ps1`; confirm the latest date is `2026-06-29`, all 33 current mother
candidates are present, and the formal cohort contains 89 records.

- [ ] **Step 2: Review commit scope**

Stage the MWP-C strategy, required runtime dependencies, pages, reports,
workflow, tests, design/plan files, and handoff. Preserve unrelated breakout
research and temporary presentation inspection files.

- [ ] **Step 3: Commit and synchronize**

Commit with a descriptive MWP-C message, fetch `origin`, rebase if remote
advanced, rerun focused verification if rebased, and push `main`.

- [ ] **Step 4: Verify remote state**

Fetch `origin` and confirm local `HEAD`, `origin/main`, and the pushed commit ID
match.
