#!/usr/bin/env python3
"""Synchronize today's market data and regenerate signal reports."""

from __future__ import annotations

import argparse

from dashboard_server import sync_market_data
from fetch_daily_trades import parse_iso_date


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync latest market data and scan strategy signals.")
    parser.add_argument("--market", default="twse,tpex", help="Comma-separated markets: twse,tpex.")
    parser.add_argument("--limit", type=int, help="Limit symbols per market for testing.")
    parser.add_argument("--workers", type=int, default=16, help="Parallel workers. Defaults to 16.")
    parser.add_argument(
        "--mode",
        choices=["auto", "daily", "symbol"],
        default="auto",
        help="auto uses whole-market daily sync first, symbol forces per-stock sync.",
    )
    parser.add_argument("--as-of", help="Target market date in YYYY-MM-DD. Defaults to today.")
    parser.add_argument(
        "--require-date",
        action="store_true",
        help="Fail instead of falling back when --as-of data has not been published yet.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    markets = [market for market in args.market.split(",") if market in {"twse", "tpex"}]
    target_date = parse_iso_date(args.as_of) if args.as_of else None
    sync_market_data(
        markets or ["twse", "tpex"],
        args.limit,
        args.workers,
        args.mode,
        target_date,
        require_target_date=args.require_date,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
