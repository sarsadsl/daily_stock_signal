#!/usr/bin/env python3
"""Synchronize today's market data and regenerate signal reports."""

from __future__ import annotations

import argparse

from dashboard_server import sync_market_data


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    markets = [market for market in args.market.split(",") if market in {"twse", "tpex"}]
    sync_market_data(markets or ["twse", "tpex"], args.limit, args.workers, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
