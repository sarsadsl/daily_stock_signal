#!/usr/bin/env python3
"""Plot candlestick charts with 5/10/20/60-day moving averages from CSV files."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

try:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
except ModuleNotFoundError:
    mdates = None
    plt = None
    Rectangle = None

from PIL import Image, ImageDraw, ImageFont


MA_WINDOWS = (5, 10, 20, 60)
MA_COLORS = {
    5: "#2563eb",
    10: "#f97316",
    20: "#16a34a",
    60: "#7c3aed",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot K-line charts from fetched CSV data.")
    parser.add_argument("csv_files", nargs="*", type=Path, help="CSV files to plot.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("charts"),
        help="Directory for PNG charts. Defaults to charts/.",
    )
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, object]]:
    def to_float(value: str) -> float | None:
        text = value.replace(",", "").strip()
        if not text or text in {"--", "---"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def to_int(value: str) -> int:
        text = value.replace(",", "").strip()
        if not text or text in {"--", "---"}:
            return 0
        return int(float(text))

    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            open_price = to_float(row["open"])
            high = to_float(row["high"])
            low = to_float(row["low"])
            close = to_float(row["close"])
            if None in {open_price, high, low, close}:
                continue
            rows.append(
                {
                    "market": row["market"],
                    "stock_no": row["stock_no"],
                    "stock_name": row["stock_name"],
                    "date": datetime.strptime(row["date"], "%Y-%m-%d"),
                    "open": float(open_price),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": to_int(row["volume_shares"]),
                }
            )
    rows.sort(key=lambda item: item["date"])
    return rows


def moving_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        result.append(total / window if index >= window - 1 else None)
    return result


def configure_font() -> None:
    if plt is None:
        return
    plt.rcParams["font.sans-serif"] = [
        "Microsoft JhengHei",
        "Noto Sans CJK TC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msjhbd.ttc") if bold else Path("C:/Windows/Fonts/msjh.ttc"),
        Path("C:/Windows/Fonts/mingliu.ttc"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def plot_chart_pillow(csv_path: Path, output_dir: Path) -> Path:
    rows = read_rows(csv_path)
    if not rows:
        raise RuntimeError(f"No rows found in {csv_path}")

    visible_rows = rows[-160:]
    width, height = 1400, 820
    margin_left, margin_right = 86, 44
    margin_top, margin_bottom = 76, 76
    price_height = 500
    volume_top = margin_top + price_height + 44
    volume_height = height - volume_top - margin_bottom
    plot_width = width - margin_left - margin_right

    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    title_font = load_font(24, bold=True)
    label_font = load_font(17)
    small_font = load_font(14)

    stock_no = str(visible_rows[0]["stock_no"])
    stock_name = str(visible_rows[0]["stock_name"])
    market = str(visible_rows[0]["market"]).upper()
    title = f"{market} {stock_no} {stock_name} K線圖  5MA / 10MA / 20MA / 60MA"
    draw.text((margin_left, 26), title, fill="#111827", font=title_font)

    closes = [float(row["close"]) for row in visible_rows]
    highs = [float(row["high"]) for row in visible_rows]
    lows = [float(row["low"]) for row in visible_rows]
    volumes = [int(row["volume"]) for row in visible_rows]
    ma_values = {window: moving_average([float(row["close"]) for row in rows], window)[-len(visible_rows):] for window in MA_WINDOWS}

    price_min = min(lows)
    price_max = max(highs)
    padding = max((price_max - price_min) * 0.08, price_max * 0.01, 1)
    price_min -= padding
    price_max += padding
    max_volume = max(volumes) or 1

    def x_at(index: int) -> float:
        if len(visible_rows) == 1:
            return margin_left + plot_width / 2
        return margin_left + index * plot_width / (len(visible_rows) - 1)

    def price_y(value: float) -> float:
        return margin_top + (price_max - value) / (price_max - price_min) * price_height

    def volume_y(value: int) -> float:
        return volume_top + volume_height - value / max_volume * volume_height

    for step in range(6):
        y = margin_top + step * price_height / 5
        price = price_max - step * (price_max - price_min) / 5
        draw.line((margin_left, y, width - margin_right, y), fill="#e5e7eb", width=1)
        draw.text((12, y - 9), f"{price:.2f}", fill="#4b5563", font=small_font)

    draw.rectangle((margin_left, margin_top, width - margin_right, margin_top + price_height), outline="#d1d5db", width=1)
    draw.rectangle((margin_left, volume_top, width - margin_right, volume_top + volume_height), outline="#d1d5db", width=1)

    candle_width = max(3, min(10, int(plot_width / max(len(visible_rows), 1) * 0.62)))
    for index, row in enumerate(visible_rows):
        x = x_at(index)
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        up = close >= open_price
        color = "#dc2626" if up else "#16a34a"

        draw.line((x, price_y(low), x, price_y(high)), fill=color, width=2)
        top = price_y(max(open_price, close))
        bottom = price_y(min(open_price, close))
        if abs(bottom - top) < 2:
            bottom = top + 2
        draw.rectangle((x - candle_width / 2, top, x + candle_width / 2, bottom), fill=color, outline=color)
        draw.rectangle((x - candle_width / 2, volume_y(int(row["volume"])), x + candle_width / 2, volume_top + volume_height), fill=color)

    for window in MA_WINDOWS:
        points = []
        for index, value in enumerate(ma_values[window]):
            if value is None:
                continue
            points.append((x_at(index), price_y(float(value))))
        if len(points) >= 2:
            draw.line(points, fill=MA_COLORS[window], width=3)

    legend_x = margin_left
    for window in MA_WINDOWS:
        draw.line((legend_x, height - 36, legend_x + 34, height - 36), fill=MA_COLORS[window], width=4)
        draw.text((legend_x + 42, height - 47), f"{window}MA", fill="#111827", font=label_font)
        legend_x += 112

    tick_indexes = sorted(set([0, len(visible_rows) // 4, len(visible_rows) // 2, len(visible_rows) * 3 // 4, len(visible_rows) - 1]))
    for index in tick_indexes:
        row = visible_rows[index]
        x = x_at(index)
        label = row["date"].strftime("%Y-%m-%d")
        draw.line((x, volume_top + volume_height, x, volume_top + volume_height + 6), fill="#6b7280", width=1)
        draw.text((x - 42, volume_top + volume_height + 10), label, fill="#4b5563", font=small_font)

    last = visible_rows[-1]
    last_text = f"最新 {last['date'].strftime('%Y-%m-%d')}  收盤 {float(last['close']):.2f}  成交量 {int(last['volume']) / 10000:.0f}萬"
    draw.text((margin_left, margin_top + price_height + 12), last_text, fill="#111827", font=label_font)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{csv_path.stem}_kline_ma.png"
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def plot_chart(csv_path: Path, output_dir: Path) -> Path:
    if plt is None or mdates is None or Rectangle is None:
        return plot_chart_pillow(csv_path, output_dir)

    rows = read_rows(csv_path)
    if not rows:
        raise RuntimeError(f"No rows found in {csv_path}")

    configure_font()

    dates = [mdates.date2num(row["date"]) for row in rows]
    opens = [float(row["open"]) for row in rows]
    highs = [float(row["high"]) for row in rows]
    lows = [float(row["low"]) for row in rows]
    closes = [float(row["close"]) for row in rows]
    volumes = [int(row["volume"]) for row in rows]
    stock_no = str(rows[0]["stock_no"])
    stock_name = str(rows[0]["stock_name"])
    market = str(rows[0]["market"]).upper()

    fig, (ax_price, ax_volume) = plt.subplots(
        2,
        1,
        figsize=(16, 9),
        dpi=150,
        sharex=True,
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.05},
    )

    candle_width = 0.62
    for x, open_price, high_price, low_price, close_price in zip(dates, opens, highs, lows, closes):
        up = close_price >= open_price
        color = "#dc2626" if up else "#16a34a"
        lower = min(open_price, close_price)
        height = abs(close_price - open_price) or 0.01
        ax_price.vlines(x, low_price, high_price, color=color, linewidth=1.0)
        ax_price.add_patch(
            Rectangle(
                (x - candle_width / 2, lower),
                candle_width,
                height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.8,
                alpha=0.9,
            )
        )

    for window in MA_WINDOWS:
        ma_values = moving_average(closes, window)
        x_values = [x for x, value in zip(dates, ma_values) if value is not None]
        y_values = [value for value in ma_values if value is not None]
        ax_price.plot(
            x_values,
            y_values,
            label=f"{window}MA",
            color=MA_COLORS[window],
            linewidth=1.35,
        )

    volume_colors = ["#dc2626" if close >= open_ else "#16a34a" for open_, close in zip(opens, closes)]
    ax_volume.bar(dates, volumes, color=volume_colors, width=candle_width, alpha=0.35)

    title = f"{market} {stock_no} {stock_name} K-line with 5MA / 10MA / 20MA / 60MA"
    ax_price.set_title(title, loc="left", fontsize=14, fontweight="bold")
    ax_price.set_ylabel("Price")
    ax_volume.set_ylabel("Volume")
    ax_price.legend(loc="upper left", ncol=4, frameon=False)
    ax_price.grid(True, color="#e5e7eb", linewidth=0.8)
    ax_volume.grid(True, axis="y", color="#e5e7eb", linewidth=0.8)

    ax_price.set_xlim(dates[0] - 3, dates[-1] + 3)
    ax_price.xaxis_date()
    ax_volume.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax_volume.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax_volume.get_xticklabels(), rotation=45, ha="right")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{csv_path.stem}_kline_ma.png"
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> int:
    args = parse_args()
    csv_files = args.csv_files or sorted(Path("data").glob("*.csv"))
    if not csv_files:
        raise SystemExit("No CSV files provided and no files found under data/.")

    for csv_path in csv_files:
        output_path = plot_chart(csv_path, args.output_dir)
        print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
