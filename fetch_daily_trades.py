#!/usr/bin/env python3
"""Fetch one year of daily stock trading data from TWSE or TPEx."""

from __future__ import annotations

import argparse
import csv
import json
import ssl
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


TWSE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"

FIELDS = [
    "market",
    "stock_no",
    "stock_name",
    "date",
    "roc_date",
    "volume_shares",
    "turnover_twd",
    "open",
    "high",
    "low",
    "close",
    "change",
    "transactions",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch daily trading data for a TWSE-listed or TPEx-listed stock."
    )
    parser.add_argument(
        "--market",
        required=True,
        choices=["twse", "tpex"],
        help="twse for listed stocks, tpex for OTC stocks.",
    )
    parser.add_argument("--stock", required=True, help="Stock code, for example 2330 or 8299.")
    parser.add_argument("--name", default="", help="Optional stock name written to the CSV.")
    parser.add_argument(
        "--start",
        help="Start date in YYYY-MM-DD. Defaults to one year before --end.",
    )
    parser.add_argument(
        "--end",
        default=date.today().isoformat(),
        help="End date in YYYY-MM-DD. Defaults to today.",
    )
    parser.add_argument(
        "--years",
        type=float,
        default=1,
        help="Years to fetch when --start is omitted. Defaults to 1.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="CSV output path. Defaults to data/{market}_{stock}_{start}_{end}.csv.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.8,
        help="Seconds to wait between monthly requests. Defaults to 0.8.",
    )
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def month_starts(start: date, end: date) -> list[date]:
    cursor = date(start.year, start.month, 1)
    months: list[date] = []
    while cursor <= end:
        months.append(cursor)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def roc_to_iso(value: str) -> str:
    parts = [int("".join(ch for ch in part if ch.isdigit())) for part in value.strip().split("/")]
    if len(parts) != 3:
        raise ValueError(f"Unexpected ROC date: {value}")
    return date(parts[0] + 1911, parts[1], parts[2]).isoformat()


def clean_int(value: str) -> int:
    value = value.replace(",", "").strip()
    if value in {"", "--", "---"}:
        return 0
    return int(value)


def clean_float_text(value: str) -> str:
    return value.replace(",", "").strip()


def ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


class RedirectHandler(HTTPRedirectHandler):
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, code, msg, headers)


def request_json(url: str, params: dict[str, str], method: str = "GET") -> dict[str, Any]:
    encoded = urlencode(params).encode("utf-8")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    if method == "GET":
        request = Request(f"{url}?{encoded.decode('utf-8')}", headers=headers)
    else:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        request = Request(url, data=encoded, headers=headers, method=method)

    try:
        opener = build_opener(HTTPSHandler(context=ssl_context()), RedirectHandler)
        with opener.open(request, timeout=30) as response:
            body = response.read().decode("utf-8-sig")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to connect to {url}: {exc.reason}") from exc

    return json.loads(body)


def fetch_twse_month(stock: str, stock_name: str, month: date) -> list[dict[str, Any]]:
    payload = request_json(
        TWSE_URL,
        {
            "response": "json",
            "date": month.strftime("%Y%m%d"),
            "stockNo": stock,
        },
    )
    if payload.get("stat") != "OK":
        raise RuntimeError(f"TWSE returned {payload.get('stat')!r} for {stock} {month:%Y-%m}")

    rows = []
    for item in payload.get("data", []):
        rows.append(
            {
                "market": "twse",
                "stock_no": stock,
                "stock_name": stock_name,
                "date": roc_to_iso(item[0]),
                "roc_date": item[0],
                "volume_shares": clean_int(item[1]),
                "turnover_twd": clean_int(item[2]),
                "open": clean_float_text(item[3]),
                "high": clean_float_text(item[4]),
                "low": clean_float_text(item[5]),
                "close": clean_float_text(item[6]),
                "change": clean_float_text(item[7]),
                "transactions": clean_int(item[8]),
            }
        )
    return rows


def fetch_tpex_month(stock: str, stock_name: str, month: date) -> list[dict[str, Any]]:
    payload = request_json(
        TPEX_URL,
        {
            "response": "json",
            "code": stock,
            "date": month.strftime("%Y/%m/%d"),
        },
        method="POST",
    )
    if payload.get("stat") != "ok":
        raise RuntimeError(f"TPEx returned {payload.get('stat')!r} for {stock} {month:%Y-%m}")

    name = stock_name or payload.get("name", "")
    table = payload.get("tables", [{}])[0]
    rows = []
    for item in table.get("data", []):
        # TPEx reports volume in trading units (1 unit = 1,000 shares) and turnover in NTD thousands.
        rows.append(
            {
                "market": "tpex",
                "stock_no": stock,
                "stock_name": name,
                "date": roc_to_iso(item[0]),
                "roc_date": item[0],
                "volume_shares": clean_int(item[1]) * 1000,
                "turnover_twd": clean_int(item[2]) * 1000,
                "open": clean_float_text(item[3]),
                "high": clean_float_text(item[4]),
                "low": clean_float_text(item[5]),
                "close": clean_float_text(item[6]),
                "change": clean_float_text(item[7]),
                "transactions": clean_int(item[8]),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    end = parse_iso_date(args.end)
    start = parse_iso_date(args.start) if args.start else end - timedelta(days=round(365 * args.years))
    if start > end:
        raise SystemExit("--start must be earlier than or equal to --end")

    fetch_month = fetch_twse_month if args.market == "twse" else fetch_tpex_month
    rows: list[dict[str, Any]] = []
    for month in month_starts(start, end):
        rows.extend(fetch_month(args.stock, args.name, month))
        time.sleep(args.sleep)

    rows = [row for row in rows if start.isoformat() <= row["date"] <= end.isoformat()]
    rows.sort(key=lambda row: row["date"])

    output = args.output or Path("data") / f"{args.market}_{args.stock}_{start}_{end}.csv"
    write_csv(output, rows)
    print(f"Wrote {len(rows)} rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
