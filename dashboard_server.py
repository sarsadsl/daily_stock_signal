#!/usr/bin/env python3
"""Local dashboard server with market-data sync progress APIs."""

from __future__ import annotations

import csv
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from alert_signals import build_message, write_reports
from fetch_daily_trades import FIELDS, clean_float_text, clean_int, parse_iso_date, request_json
from fetch_market_all import Symbol, fetch_symbol, listed_stock_symbols, read_symbols, write_csv, write_symbols
from run_market_backtest import STRATEGIES, Row, prepare, read_rows, value_at
from signal_scoring import signal_score


HOST = "127.0.0.1"
PORT = 8766
DATA_DIRS = {"twse": Path("data/all_twse"), "tpex": Path("data/all_tpex")}
STATUS_LOCK = threading.Lock()
SYNC_THREAD: threading.Thread | None = None
STATUS: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "total": 0,
    "completed": 0,
    "failed": 0,
    "matches": 0,
    "current": "",
    "message": "待命",
    "log": [],
    "last_match": None,
}
DEFAULT_WORKERS = 16
MIN_SIGNAL_VOLUME_SHARES = 1_000_000
TWSE_DAILY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_DAILY_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"


def update_status(**changes: Any) -> None:
    with STATUS_LOCK:
        STATUS.update(changes)
        STATUS["percent"] = round(min(100, (STATUS["completed"] / STATUS["total"]) * 100), 1) if STATUS["total"] else 0


def append_log(message: str) -> None:
    with STATUS_LOCK:
        log = STATUS.setdefault("log", [])
        log.append({"time": time.strftime("%H:%M:%S"), "message": message})
        del log[:-80]


def status_snapshot() -> dict[str, Any]:
    with STATUS_LOCK:
        return json.loads(json.dumps(STATUS, ensure_ascii=False))


def display_match_count(matches: list[dict[str, Any]]) -> int:
    return len({(item.get("market"), item.get("stock_no"), item.get("date")) for item in matches})


def latest_existing_csv(directory: Path, code: str) -> Path | None:
    files = [path for path in directory.glob(f"{code}_*.csv") if not path.name.startswith("_")]
    if not files:
        return None
    return max(files, key=lambda path: (path.stat().st_mtime, path.name))


def symbols_from_existing_csvs(market: str) -> list[Symbol]:
    directory = DATA_DIRS[market]
    by_code: dict[str, Symbol] = {}
    if not directory.exists():
        return []
    for path in directory.glob("*.csv"):
        if path.name.startswith("_"):
            continue
        code = path.name.split("_", 1)[0]
        if not re.fullmatch(r"\d{4}", code):
            continue
        name = ""
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
                first = next(csv.DictReader(csvfile), None)
                if first:
                    name = str(first.get("stock_name", "")).strip()
        except Exception:
            name = ""
        current = by_code.get(code)
        if current is None or (not current.name and name):
            by_code[code] = Symbol(code=code, name=name)
    return [by_code[code] for code in sorted(by_code)]


def read_raw_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        return list(csv.DictReader(csvfile))


def append_csv_row(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDS)
        writer.writerow(row)


def first_of_month(value: date) -> date:
    return date(value.year, value.month, 1)


def iso_to_roc(value: date) -> str:
    return f"{value.year - 1911:03d}/{value.month:02d}/{value.day:02d}"


def strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


def normalize_change(sign_html: str, diff_text: str) -> str:
    diff = clean_float_text(strip_html(diff_text))
    if diff in {"", "--", "---"}:
        return diff
    sign_text = strip_html(sign_html)
    if "-" in sign_text or "green" in sign_html.lower():
        return diff if diff.startswith("-") else f"-{diff}"
    if "+" in sign_text or "red" in sign_html.lower():
        return diff if diff.startswith("+") else f"+{diff}"
    return diff


def normalize_price(value: str) -> str:
    return clean_float_text(strip_html(value))


def fetch_twse_daily_rows(target_date: date) -> dict[str, dict[str, Any]]:
    payload = request_json(
        TWSE_DAILY_URL,
        {
            "response": "json",
            "date": target_date.strftime("%Y%m%d"),
            "type": "ALLBUT0999",
        },
    )
    table = next(
        (
            item
            for item in payload.get("tables", [])
            if item.get("fields", [])[:2] == ["證券代號", "證券名稱"]
        ),
        None,
    )
    if table is None:
        raise RuntimeError("TWSE daily table not found")

    rows: dict[str, dict[str, Any]] = {}
    for item in table.get("data", []):
        code = str(item[0]).strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        rows[code] = {
            "market": "twse",
            "stock_no": code,
            "stock_name": str(item[1]).strip(),
            "date": target_date.isoformat(),
            "roc_date": iso_to_roc(target_date),
            "volume_shares": clean_int(item[2]),
            "turnover_twd": clean_int(item[4]),
            "open": normalize_price(item[5]),
            "high": normalize_price(item[6]),
            "low": normalize_price(item[7]),
            "close": normalize_price(item[8]),
            "change": normalize_change(item[9], item[10]),
            "transactions": clean_int(item[3]),
        }
    return rows


def fetch_tpex_daily_rows(target_date: date) -> dict[str, dict[str, Any]]:
    payload = request_json(
        TPEX_DAILY_URL,
        {
            "response": "json",
            "date": target_date.strftime("%Y/%m/%d"),
            "type": "EW",
        },
    )
    table = next(
        (
            item
            for item in payload.get("tables", [])
            if item.get("fields", [])[:2] == ["代號", "名稱"]
        ),
        None,
    )
    if table is None:
        raise RuntimeError("TPEx daily table not found")

    rows: dict[str, dict[str, Any]] = {}
    for item in table.get("data", []):
        code = str(item[0]).strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        rows[code] = {
            "market": "tpex",
            "stock_no": code,
            "stock_name": str(item[1]).strip(),
            "date": target_date.isoformat(),
            "roc_date": table.get("date", iso_to_roc(target_date)),
            "volume_shares": clean_int(item[7]),
            "turnover_twd": clean_int(item[8]),
            "open": normalize_price(item[4]),
            "high": normalize_price(item[5]),
            "low": normalize_price(item[6]),
            "close": normalize_price(item[2]),
            "change": normalize_price(item[3]),
            "transactions": clean_int(item[9]),
        }
    return rows


def fetch_daily_rows(market: str, target_date: date) -> dict[str, dict[str, Any]]:
    if market == "twse":
        return fetch_twse_daily_rows(target_date)
    if market == "tpex":
        return fetch_tpex_daily_rows(target_date)
    raise ValueError(f"Unsupported market: {market}")


def fetch_latest_daily_rows(
    markets: list[str],
    preferred_date: date,
    max_lookback_days: int = 10,
) -> tuple[date, dict[str, dict[str, dict[str, Any]]]]:
    errors: list[str] = []
    for offset in range(max_lookback_days + 1):
        target_date = preferred_date - timedelta(days=offset)
        daily_rows: dict[str, dict[str, dict[str, Any]]] = {}
        try:
            for market in markets:
                rows = fetch_daily_rows(market, target_date)
                if not rows:
                    raise RuntimeError(f"{market.upper()} no rows")
                daily_rows[market] = rows
            return target_date, daily_rows
        except Exception as exc:
            errors.append(f"{target_date}: {exc}")
    raise RuntimeError("找不到最近已公布的全市場日資料；" + "；".join(errors[-3:]))


def load_symbols(market: str, limit: int | None) -> list[Symbol]:
    directory = DATA_DIRS[market]
    symbols_path = directory / "_symbols.csv"
    if symbols_path.exists():
        symbols = read_symbols(symbols_path)
        if symbols:
            return symbols[:limit] if limit else symbols
    merged: dict[str, Symbol] = {symbol.code: symbol for symbol in symbols_from_existing_csvs(market)}
    for symbol in listed_stock_symbols(market):
        if symbol.code not in merged or not merged[symbol.code].name:
            merged[symbol.code] = symbol
    symbols = [merged[code] for code in sorted(merged)]
    write_symbols(symbols_path, symbols)
    return symbols[:limit] if limit else symbols


def merge_rows(existing: list[dict[str, Any]], fetched: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in existing + fetched:
        row_date = row.get("date", "")
        if start.isoformat() <= row_date <= end.isoformat():
            merged[row_date] = row
    return [merged[key] for key in sorted(merged)]


def latest_csv_date(path: Path) -> date | None:
    try:
        rows = read_raw_csv(path)
    except Exception:
        return None
    dates = [row.get("date", "") for row in rows if row.get("date")]
    return parse_iso_date(max(dates)) if dates else None


def signal_rows_for_csv(path: Path) -> list[dict[str, Any]]:
    rows = read_rows(path)
    return signal_rows_for_rows(rows, path)


def rows_from_records(records: list[dict[str, Any]]) -> list[Row]:
    def to_float(value: Any) -> float | None:
        text = str(value).replace(",", "").strip()
        if not text or text in {"--", "---"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def to_int(value: Any) -> int:
        text = str(value).replace(",", "").strip()
        if not text or text in {"", "--", "---"}:
            return 0
        return int(float(text))

    rows: list[Row] = []
    for record in records:
        open_price = to_float(record.get("open", ""))
        high = to_float(record.get("high", ""))
        low = to_float(record.get("low", ""))
        close = to_float(record.get("close", ""))
        if None in {open_price, high, low, close}:
            continue
        rows.append(
            Row(
                market=str(record.get("market", "")),
                stock_no=str(record.get("stock_no", "")),
                stock_name=str(record.get("stock_name", "")),
                date=str(record.get("date", "")),
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=to_int(record.get("volume_shares", "")),
            )
        )
    rows.sort(key=lambda row: row.date)
    return rows


def signal_rows_for_records(records: list[dict[str, Any]], path: Path) -> list[dict[str, Any]]:
    rows = rows_from_records(records)
    return signal_rows_for_rows(rows, path)


def signal_rows_for_rows(rows: list[Row], path: Path) -> list[dict[str, Any]]:
    if len(rows) < 60:
        return []
    indicators = prepare(rows)
    index = len(rows) - 1
    row = rows[index]
    if row.volume < MIN_SIGNAL_VOLUME_SHARES:
        return []
    matches: list[dict[str, Any]] = []
    for strategy_name, signal in STRATEGIES.items():
        reason = signal(rows, indicators, index)
        if not reason:
            continue
        score_data = signal_score(rows, indicators, index, reason)
        matches.append(
            {
                "market": row.market.upper(),
                "stock_no": row.stock_no,
                "stock_name": row.stock_name,
                "date": row.date,
                "strategy": strategy_name,
                "reason": reason,
                **score_data,
                "close": row.close,
                "volume": row.volume,
                "ma5": value_at(indicators["ma5"], index),
                "ma10": value_at(indicators["ma10"], index),
                "ma20": value_at(indicators["ma20"], index),
                "ma60": value_at(indicators["ma60"], index),
                "source": str(path),
            }
        )
    return matches


def sync_one_symbol(market: str, symbol: Symbol, start: date, today: date) -> tuple[list[dict[str, Any]], str, bool]:
    directory = DATA_DIRS[market]
    latest_path = latest_existing_csv(directory, symbol.code)
    existing: list[dict[str, Any]] = []
    fetch_start = start
    if latest_path:
        existing = read_raw_csv(latest_path)
        dated_rows = [row for row in existing if row.get("date")]
        if dated_rows:
            latest_date = parse_iso_date(max(row["date"] for row in dated_rows))
            if latest_date >= today:
                fresh_matches = signal_rows_for_csv(latest_path)
                if fresh_matches:
                    return fresh_matches, f"{symbol.code} 已是最新，命中 {len(fresh_matches)} 筆訊號", False
                return [], f"{symbol.code} 已是最新，無訊號", False
            fetch_start = first_of_month(latest_date)

    fetched = fetch_symbol(
        market=market,
        symbol=symbol,
        start=fetch_start,
        end=today,
        sleep_month=0.0,
        jitter_month=0,
        retries=2,
    )
    merged = merge_rows(existing, fetched, start, today)
    output = directory / f"{symbol.code}_{start}_{today}.csv"
    write_csv(output, merged)
    fresh_matches = signal_rows_for_csv(output)
    if fresh_matches:
        return fresh_matches, f"{symbol.code} 命中 {len(fresh_matches)} 筆訊號", False
    return [], f"{symbol.code} 完成，無訊號", False


def sync_daily_market_data(markets: list[str], limit: int | None = None) -> bool:
    today = date.today()
    update_status(message="載入股票清單", current="TWSE + TPEx")
    symbols_by_market = {market: load_symbols(market, limit) for market in markets}
    all_symbols = [(market, symbol) for market, symbols in symbols_by_market.items() for symbol in symbols]
    matches: list[dict[str, Any]] = []

    update_status(
        running=True,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=None,
        total=len(all_symbols),
        completed=0,
        failed=0,
        matches=0,
        current="",
        message="準備同步",
        log=[],
        last_match=None,
    )
    append_log(f"快速同步開始，共 {len(all_symbols)} 檔")

    update_status(message="尋找最近已公布交易日", current=today.isoformat())
    target_date, daily_rows = fetch_latest_daily_rows(markets, today)
    start = target_date - timedelta(days=365)
    if target_date != today:
        append_log(f"{today} 尚未公布收盤資料，改用 {target_date}")
    for market in markets:
        append_log(f"{market.upper()} {target_date} 已下載 {len(daily_rows[market])} 筆日資料")

    for market, symbol in all_symbols:
        directory = DATA_DIRS[market]
        update_status(current=f"{symbol.code} {symbol.name}", message=f"合併並掃描 {market.upper()} {symbol.code}")
        try:
            latest_path = latest_existing_csv(directory, symbol.code)
            existing = read_raw_csv(latest_path) if latest_path else []
            daily_row = daily_rows.get(market, {}).get(symbol.code)
            output = latest_path or (directory / f"{symbol.code}_{start}_{target_date}.csv")
            if daily_row is None:
                if not latest_path:
                    continue
                records = existing
            else:
                if not daily_row.get("stock_name"):
                    daily_row["stock_name"] = symbol.name
                dated_rows = [row for row in existing if row.get("date")]
                latest_date = parse_iso_date(max(row["date"] for row in dated_rows)) if dated_rows else None
                if latest_path and latest_date and latest_date < target_date:
                    append_csv_row(latest_path, daily_row)
                    records = [row for row in existing + [daily_row] if start.isoformat() <= row.get("date", "") <= target_date.isoformat()]
                elif latest_path and latest_date and latest_date >= target_date:
                    records = existing
                else:
                    records = merge_rows(existing, [daily_row], start, target_date)
                    write_csv(output, records)

            fresh_matches = [
                row for row in signal_rows_for_records(records, output)
                if row.get("date") == target_date.isoformat()
            ]
            if fresh_matches:
                matches.extend(fresh_matches)
                update_status(matches=display_match_count(matches), last_match=fresh_matches[-1])
        except Exception as exc:
            update_status(failed=status_snapshot()["failed"] + 1)
            append_log(f"{symbol.code} 失敗：{exc}")
        finally:
            update_status(completed=status_snapshot()["completed"] + 1)

    matches.sort(key=lambda item: (item["market"], item["stock_no"], item["strategy"]))
    write_reports(matches, build_message(matches))
    update_status(
        running=False,
        finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        matches=display_match_count(matches),
        message=f"快速同步完成，資料日 {target_date}，命中 {display_match_count(matches)} 檔",
    )
    append_log("快速同步完成")
    return True


def sync_market_data(markets: list[str], limit: int | None, workers: int = DEFAULT_WORKERS, mode: str = "auto") -> None:
    if mode in {"auto", "daily"} and limit is None:
        try:
            sync_daily_market_data(markets, limit)
            return
        except Exception as exc:
            append_log(f"快速同步失敗：{exc}")
            update_status(
                running=False,
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                message=f"快速同步失敗：{exc}",
            )
            return

    today = date.today()
    start = today - timedelta(days=365)
    update_status(message="載入股票清單", current="TWSE + TPEx")
    all_symbols = [(market, symbol) for market in markets for symbol in load_symbols(market, limit)]
    matches: list[dict[str, Any]] = []

    update_status(
        running=True,
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=None,
        total=len(all_symbols),
        completed=0,
        failed=0,
        matches=0,
        current="",
        message="準備同步",
        log=[],
        last_match=None,
    )
    append_log(f"逐檔同步開始，共 {len(all_symbols)} 檔")

    max_workers = max(1, min(workers, 32, len(all_symbols) or 1))
    update_status(message=f"同步中：{max_workers} 線並行")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(sync_one_symbol, market, symbol, start, today): (market, symbol)
            for market, symbol in all_symbols
        }
        for future in as_completed(futures):
            market, symbol = futures[future]
            update_status(current=f"{symbol.code} {symbol.name}", message=f"掃描 {market.upper()} {symbol.code}")
            try:
                fresh_matches, message, _failed = future.result()
                if fresh_matches:
                    matches.extend(fresh_matches)
                    update_status(matches=display_match_count(matches), last_match=fresh_matches[-1])
                append_log(message)
            except Exception as exc:
                update_status(failed=status_snapshot()["failed"] + 1)
                append_log(f"{symbol.code} 失敗：{exc}")
            finally:
                update_status(completed=status_snapshot()["completed"] + 1)

    matches.sort(key=lambda item: (item["market"], item["stock_no"], item["strategy"]))
    write_reports(matches, build_message(matches))
    update_status(
        running=False,
        finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        matches=display_match_count(matches),
        message=f"同步完成，符合訊號 {display_match_count(matches)} 檔",
    )
    append_log("同步完成")


class DashboardHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self.send_json(status_snapshot())
            return
        if parsed.path == "/api/events":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_payload = ""
            while True:
                payload = json.dumps(status_snapshot(), ensure_ascii=False)
                if payload != last_payload:
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_payload = payload
                if not status_snapshot().get("running"):
                    break
                time.sleep(0.5)
            return
        super().do_GET()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_POST(self) -> None:
        global SYNC_THREAD
        parsed = urlparse(self.path)
        if parsed.path != "/api/sync":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        query = parse_qs(parsed.query)
        markets = [market for market in query.get("market", ["twse,tpex"])[0].split(",") if market in DATA_DIRS]
        limit_text = query.get("limit", [""])[0]
        limit = int(limit_text) if limit_text.isdigit() and int(limit_text) > 0 else None
        workers_text = query.get("workers", [str(DEFAULT_WORKERS)])[0]
        workers = int(workers_text) if workers_text.isdigit() and int(workers_text) > 0 else DEFAULT_WORKERS
        mode = query.get("mode", ["auto"])[0]
        if mode not in {"auto", "daily", "symbol"}:
            mode = "auto"
        if not markets:
            markets = ["twse", "tpex"]

        with STATUS_LOCK:
            if STATUS.get("running"):
                self.send_json({"ok": False, "message": "同步正在執行中"}, HTTPStatus.CONFLICT)
                return
            STATUS.update(
                running=True,
                started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                finished_at=None,
                total=0,
                completed=0,
                failed=0,
                matches=0,
                current="",
                message="同步準備中",
                log=[],
                last_match=None,
                percent=0,
            )
            SYNC_THREAD = threading.Thread(target=sync_market_data, args=(markets, limit, workers, mode), daemon=True)
            SYNC_THREAD.start()
        self.send_json({"ok": True, "message": "同步已開始"})


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Dashboard server: http://localhost:{PORT}/signal_dashboard.html")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
