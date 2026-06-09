# TWSE / TPEx Daily Trade Fetcher

這個小工具會從官方網站抓個股每日成交資訊，逐月合併後輸出 CSV。

來源：

- 上市股票：台灣證券交易所個股日成交資訊 `STOCK_DAY`
- 上櫃股票：櫃買中心個股日成交資訊 `afterTrading/tradingStock`

## 使用方式

抓上市台積電 2330 最近一年：

```powershell
python fetch_daily_trades.py --market twse --stock 2330 --name 台積電
```

抓上櫃群聯 8299 最近一年：

```powershell
python fetch_daily_trades.py --market tpex --stock 8299 --name 群聯
```

指定日期區間與輸出檔：

```powershell
python fetch_daily_trades.py --market twse --stock 2330 --name 台積電 --start 2025-05-29 --end 2026-05-29 --output data/2330.csv
```

## 互動式 K 線工具

啟動本機伺服器：

```powershell
python -m http.server 8765
```

然後用瀏覽器開啟：

```text
http://localhost:8765/interactive_kline.html
```

互動工具會讀取 `data/` 內目前的 CSV，支援股票切換、均線勾選、滑鼠提示、拖曳平移、滾輪縮放、匯入 CSV 與下載 PNG。

目前互動工具也內建 2330 台積電與 8299 群聯的策略回測：

- 台積電：5MA > 10MA > 20MA > 60MA 時，收盤跌破 20MA 買進；或 60MA 上揚時收盤跌破 60MA 買進。進場後 -15% 停損，不停利。
- 群聯：5/10/20/60MA 糾結小於 8% 後，量大於 20 日均量 1.5 倍紅 K 或跳空紅 K 買進；或 5/20/60MA 上揚且價格回到 20MA 3% 內買進。進場後 -15% 停損，不停利。

期末仍持有的部位會用最後一日收盤價估值，方便計算這一年報酬率。

群聯目前另有一組人工指定樣本買點，用來校準策略條件：

`2025-09-05, 2025-09-26, 2025-10-27, 2025-11-05, 2025-12-22, 2026-03-09, 2026-04-28`

台積電人工指定樣本買點：

`2025-09-10, 2025-11-24, 2025-12-18, 2026-02-06, 2026-03-09, 2026-03-31`

策略互套比較也會顯示在互動工具中：

- 台積電策略套台積電
- 台積電策略套群聯
- 群聯策略套群聯
- 群聯策略套台積電

## 全市場批次抓取任務

上市全股票：

```powershell
python fetch_all_twse_task.py --start 2025-05-29 --end 2026-05-29 --output-dir data/all_twse --resume
```

上櫃全股票：

```powershell
python fetch_all_tpex_task.py --start 2025-05-29 --end 2026-05-29 --output-dir data/all_tpex --resume
```

先測前 5 檔：

```powershell
python fetch_all_twse_task.py --limit 5 --start 2025-05-29 --end 2026-05-29 --output-dir data/all_twse_test
python fetch_all_tpex_task.py --limit 5 --start 2025-05-29 --end 2026-05-29 --output-dir data/all_tpex_test
```

任務會先寫出 `_symbols.csv`，每檔股票各自輸出一個 CSV，並用 `_checkpoint.json` 記錄完成與失敗清單。若中斷，重新加上 `--resume` 會跳過已完成股票。

將目前已抓到的全市場 CSV 匯入互動工具：

```powershell
python build_market_index.py
```

這會產生 `data/market_index.json`。重新整理 `interactive_kline.html` 後，互動工具會載入索引內股票，並在「策略互套比較」中分別套用台積電策略與群聯策略做回測排序。

## 輸出欄位

CSV 欄位統一為：

`market, stock_no, stock_name, date, roc_date, volume_shares, turnover_twd, open, high, low, close, change, transactions`

注意：櫃買中心原始資料的成交量單位是張、成交金額單位是仟元；程式會換算成股與元，方便和 TWSE 對齊。

## 每日策略警示

`alert_signals.py` 會掃描 `data/all_twse`、`data/all_tpex` 和單檔範例資料的最新交易日，套用目前回測檔裡的策略，產生符合進場條件的清單。

先用 dry-run 測試：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" alert_signals.py --dry-run
```

輸出檔會寫在：

- `reports/daily_signal_alert.txt`
- `reports/daily_signal_alert.csv`
- `reports/daily_signal_alert.json`

### 設定通知

可擇一設定通知管道。若沒有設定，程式仍會產生報告，但不會傳送訊息。

LINE Messaging API：

```powershell
[Environment]::SetEnvironmentVariable("LINE_CHANNEL_ACCESS_TOKEN", "你的 channel access token", "User")
[Environment]::SetEnvironmentVariable("LINE_USER_ID", "你的 user id", "User")
```

只透過 LINE 傳送：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" alert_signals.py --channel line
```

只傳送特定訊號可加篩選條件：

```powershell
# 只送群聯策略
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" alert_signals.py --channel line --strategy "群聯策略"

# 只送指定股票代號
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" alert_signals.py --channel line --stock 2330,8299

# 只送上櫃且訊號原因包含「回測」的結果
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" alert_signals.py --channel line --market tpex --reason-contains "回測"
```

產生前幾檔訊號的 K 線圖：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" alert_signals.py --dry-run --chart-items 3 --max-items 3
```

K 線圖會輸出到 `charts/daily_alert/`，訊息內也會列出圖檔路徑。

LINE 圖片訊息要求圖片必須是公開 HTTPS URL，不能直接傳本機檔案。若已把 `charts/daily_alert/` 放到可公開讀取的 HTTPS 網址，可設定：

```powershell
[Environment]::SetEnvironmentVariable("ALERT_IMAGE_BASE_URL", "https://你的網域/charts/daily_alert", "User")
```

之後執行時加上 `--chart-items`，LINE 會在文字後附上最多 4 張 K 線圖：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" alert_signals.py --channel line --chart-items 4 --max-items 4
```

Telegram：

```powershell
[Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "你的 bot token", "User")
[Environment]::SetEnvironmentVariable("TELEGRAM_CHAT_ID", "你的 chat id", "User")
```

Telegram 可直接上傳本機 K 線圖，不需要公開 HTTPS 圖床：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" alert_signals.py --channel telegram --chart-items 4 --max-items 4
```

Discord 或其他 webhook：

```powershell
[Environment]::SetEnvironmentVariable("ALERT_WEBHOOK_URL", "你的 webhook url", "User")
```

預設只把前 30 筆放進手機訊息，完整清單看 CSV。可用 `ALERT_MAX_ITEMS` 調整：

```powershell
[Environment]::SetEnvironmentVariable("ALERT_MAX_ITEMS", "50", "User")
```

### 建立每天晚上 8 點排程

在 PowerShell 執行：

```powershell
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"C:\Users\a1430\Documents\月季線訊號\run_daily_alert.ps1`""
$Trigger = New-ScheduledTaskTrigger -Daily -At 20:00
Register-ScheduledTask -TaskName "DailyStockSignalAlert" -Action $Action -Trigger $Trigger -Description "每天晚上 8 點傳送策略股票警示" -Force
```

若想手動跑一次：

```powershell
.\run_daily_alert.ps1
```

### 網頁訊號看板

啟動本機網頁服務：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" dashboard_server.py
```

打開：

```text
http://localhost:8766/signal_dashboard.html
```

看板會讀取 `reports/daily_signal_alert.json`，重新執行每日警示後刷新頁面即可看到最新訊號。
若要使用「同步今日資料」按鈕，必須用 `dashboard_server.py` 啟動，單純的 `python -m http.server` 只能瀏覽既有報告，不能呼叫同步 API。

手動同步今日資料並重新產生訊號報告：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" sync_today.py
```

同步檔數以唯一股票代號計算，會合併既有 CSV 檔案庫與 `_symbols.csv`。若要調整同步速度，可設定並行數：

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" sync_today.py --workers 6
```
