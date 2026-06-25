#!/usr/bin/env python3
"""Lifecycle filters shared by pullback/MWP reports."""

from __future__ import annotations

from typing import Any, Callable


SeriesFinder = Callable[[dict[Any, Any], str, str], tuple[list[Any], dict[str, list[float | None]], dict[str, int]] | None]


def _stock_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("market") or "").upper(), str(row.get("stock_no") or ""))


def _date_index(
    row: dict[str, Any],
    series: dict[Any, Any],
    find_series: SeriesFinder,
    date_key: str,
) -> int | None:
    market, stock_no = _stock_key(row)
    bundle = find_series(series, market, stock_no)
    if not bundle:
        return None
    _, _, dates = bundle
    value = row.get(date_key)
    if value is None:
        return None
    return dates.get(str(value))


def filter_same_stock_mother_entries(
    rows: list[dict[str, Any]],
    series: dict[Any, Any],
    find_series: SeriesFinder,
    *,
    cooldown_trading_days: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Remove duplicate mother/base entries for the same stock lifecycle.

    Rules:
    - A same-stock mother/base entry is rejected while a prior accepted mother is still open.
    - A same-stock mother/base entry is rejected if there was an accepted buy in the prior
      ``cooldown_trading_days`` trading sessions.

    The function returns accepted rows and diagnostics. Rows are copied before returning so the
    original upstream report payload is not mutated.
    """

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    accepted_by_stock: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ordered = sorted(rows, key=lambda row: (str(row.get("entry_date") or ""), str(row.get("signal_date") or ""), str(row.get("market") or ""), str(row.get("stock_no") or "")))

    for source in ordered:
        row = dict(source)
        key = _stock_key(row)
        entry_index = _date_index(row, series, find_series, "entry_date")
        exit_index = _date_index(row, series, find_series, "exit_date")
        reason = None
        prior_match: dict[str, Any] | None = None

        for prior in accepted_by_stock.get(key, []):
            prior_entry_index = prior.get("_lifecycle_entry_index")
            prior_exit_index = prior.get("_lifecycle_exit_index")
            if entry_index is not None and prior_exit_index is not None and entry_index <= prior_exit_index:
                reason = "same_stock_mother_still_open"
                prior_match = prior
                break
            if entry_index is not None and prior_entry_index is not None:
                gap = entry_index - prior_entry_index
                if 0 <= gap <= cooldown_trading_days:
                    reason = "same_stock_buy_cooldown"
                    prior_match = prior
                    break
            elif str(row.get("entry_date") or "") <= str(prior.get("exit_date") or ""):
                reason = "same_stock_mother_still_open_date_fallback"
                prior_match = prior
                break

        row["_lifecycle_entry_index"] = entry_index
        row["_lifecycle_exit_index"] = exit_index
        if reason:
            row["lifecycle_filter_reject_reason"] = reason
            if prior_match:
                row["lifecycle_filter_prior_signal_date"] = prior_match.get("signal_date")
                row["lifecycle_filter_prior_entry_date"] = prior_match.get("entry_date")
                row["lifecycle_filter_prior_exit_date"] = prior_match.get("exit_date")
            rejected.append(row)
            continue

        row["lifecycle_filter"] = f"same-stock active-mother and {cooldown_trading_days}-trading-day buy cooldown"
        accepted.append(row)
        accepted_by_stock.setdefault(key, []).append(row)

    def strip_internal(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if not key.startswith("_lifecycle_")}

    accepted_clean = [strip_internal(row) for row in accepted]
    rejected_clean = [strip_internal(row) for row in rejected]
    diagnostics = {
        "input_rows": len(rows),
        "accepted_rows": len(accepted_clean),
        "rejected_rows": len(rejected_clean),
        "cooldown_trading_days": cooldown_trading_days,
        "rejection_counts": {
            reason: sum(1 for row in rejected_clean if row.get("lifecycle_filter_reject_reason") == reason)
            for reason in sorted({str(row.get("lifecycle_filter_reject_reason")) for row in rejected_clean})
        },
        "rejected_examples": rejected_clean,
    }
    return accepted_clean, diagnostics
