#!/usr/bin/env python3
"""Build an index of currently available market CSV files for the interactive tool."""

from __future__ import annotations

import csv
import json
from pathlib import Path


DATA_DIRS = [
    ("twse", Path("data/all_twse")),
    ("tpex", Path("data/all_tpex")),
]


def first_data_row(path: Path) -> dict[str, str] | None:
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        return next(reader, None)


def build_index() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for market, directory in DATA_DIRS:
        if not directory.exists():
            continue
        latest_by_code: dict[str, Path] = {}
        for path in sorted(directory.glob("*.csv")):
            if path.name.startswith("_"):
                continue
            code = path.name.split("_", 1)[0]
            current = latest_by_code.get(code)
            if current is None or (path.stat().st_mtime, path.name) > (current.stat().st_mtime, current.name):
                latest_by_code[code] = path

        for path in sorted(latest_by_code.values(), key=lambda item: item.name):
            row = first_data_row(path)
            if not row:
                continue
            stock_no = row.get("stock_no", path.stem.split("_", 1)[0])
            stock_name = row.get("stock_name", "")
            items.append(
                {
                    "label": f"{stock_no} {stock_name} {market.upper()}",
                    "market": market,
                    "stock_no": stock_no,
                    "stock_name": stock_name,
                    "path": path.as_posix(),
                }
            )
    return items


def main() -> int:
    items = build_index()
    output = Path("data/market_index.json")
    output.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(items)} items to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
