#!/usr/bin/env python3
"""Small task: fetch daily trades for every TPEx listed company."""

from __future__ import annotations

import sys

from fetch_market_all import main


if __name__ == "__main__":
    sys.argv.insert(1, "--market")
    sys.argv.insert(2, "tpex")
    raise SystemExit(main())
