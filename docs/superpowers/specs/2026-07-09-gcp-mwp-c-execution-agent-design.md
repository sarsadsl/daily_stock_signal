# GCP MWP-C Execution Agent 設計規格

日期：2026-07-09

## 目標

建立一套部署在 Google Cloud Compute Engine 的常駐 execution agent，專門負責 MWP-C 正式追蹤的盤前、開盤、持倉監控與下單執行流程，避免再依賴 GitHub Actions 排程處理 09:00 敏感時點任務。

這套 agent 必須：

- 不改動現有正式追蹤策略判斷來源
- 與現有網站/報表建置流程分離
- 準時處理 `正式追蹤買進 call 訊`
- 保留未來接券商 WebSocket、沙盒單、正式單的擴充空間

## 非目標

- 本次不重寫 `build_mwp_a_strategy_tracking.py` 的正式追蹤邏輯
- 本次不把網站改成動態後端應用
- 本次不把 GitHub 報表/部署流程搬離現有 repo
- 本次不直接啟用正式下單

## 現況與問題

目前正式追蹤買進 call 使用 GitHub Actions workflow `MWP-C Open Entry Call` 排程執行。雖然 workflow 設定為台北時間 09:06，但實際執行曾延遲到中午，導致即使有符合條件的個股，也無法在開盤附近準時收到 Telegram 通知。

2026-07-09 的實際驗證已證明：

- 當日有 31 檔 `待次日開盤`
- 其中 2 檔符合正式追蹤開盤進場門檻
- 但 GitHub Actions 在 10:45 台北時間仍未執行

根因不是策略錯誤，也不是 Telegram 壞掉，而是 GitHub 排程本身不適合處理開盤敏感任務。

## 核心原則

1. 正式追蹤資料仍以 `reports/mwp_a_strategy_tracking.json` 的 `tracking.formal_forward_records` 為唯一來源。
2. 晚上資料建置、網站部署、報表更新仍留在現有 repo / GitHub 流程。
3. 早盤進場 call、持倉監控、下單執行搬到雲端常駐 agent。
4. Agent 只消費正式追蹤資料，不自行重新判斷策略。
5. 所有可交易事件都必須留下可稽核紀錄。

## 部署目標

### 雲端平台

- Google Cloud
- 服務：Compute Engine
- 區域：`asia-east1`
- 作業系統：Ubuntu LTS

選擇原因：

- 接近台股市場時間需求
- 適合常駐服務與 WebSocket 連線
- 容易擴充到持倉監控與自動下單

## 架構總覽

系統分成兩層：

### 1. 既有 nightly data pipeline

保留在目前 repo 與 GitHub 流程中：

- 市場資料同步
- 正式追蹤 JSON 產生
- 網站建置與部署
- 晚間 Telegram 訊號通知

### 2. 新增 cloud execution agent

部署在 GCP VM，負責：

- 同步最新正式追蹤資料
- 開盤前載入 `待次日開盤` 名單
- 取得開盤價
- 判斷是否符合正式追蹤買進門檻
- 發送 Telegram call 訊
- 寫入 call log
- 沙盒下單
- 未來正式下單
- 持倉監控與出場執行

## 元件設計

### tracking-sync

用途：

- 從 GitHub raw 檔或同步後的 repo 讀取最新 `reports/mwp_a_strategy_tracking.json`
- 驗證 JSON 結構
- 產出 agent 內部可直接使用的 pending entry 清單

輸入：

- `reports/mwp_a_strategy_tracking.json`

輸出：

- `formal_forward_records`
- 今日待開盤判斷清單

### open-entry-runner

用途：

- 在交易日早盤執行正式追蹤進場判斷
- 只對 `待次日開盤` 記錄進行處理

規則：

- 僅處理 next trading date 等於當日者
- 僅處理未發送過 call 的記錄
- 僅在 `open_price <= entry_limit_price` 時判定為 `called`

處理結果：

- `called`
- `open_failed`
- `missing_open_quote`
- `skipped_already_processed`

### quote-gateway

用途：

- 取得開盤價與後續行情

階段規劃：

1. 第一階段：沿用現有公開市場資料來源作為開盤驗證
2. 第二階段：接券商 API snapshot / quote
3. 第三階段：接券商 WebSocket 作為主要價格來源

原則：

- 對正式追蹤買進判斷，必須使用可明確代表當日開盤價的資料
- 不能只憑收到的第一筆即時訊息就視為正式開盤價，除非券商 API 明確定義該欄位

### telegram-notifier

用途：

- 沿用既有 Telegram 發送通道
- 由 execution agent 主動發送開盤 call 訊

訊息原則：

- 簡潔
- 明確顯示股票、訊號日、進場上限、實際開盤價
- 可擴充為包含沙盒單回報狀態

### order-adapter

用途：

- 抽象化下單執行層

模式：

- `noop`：只記錄，不下單
- `sandbox`：送沙盒單
- `live`：送正式單

第一階段只需要：

- 接永豐沙盒
- 將正式追蹤進出場事件同步到 sandbox ledger

### state-store

用途：

- 持久化儲存 agent 狀態

第一階段儲存內容：

- open entry call log
- sandbox orders
- sandbox fills
- positions
- heartbeat
- error events

資料庫選擇：

- 第一階段使用 SQLite
- 未來如需多程序/多節點再升級 Postgres

## 執行流程

### 每日收盤後

1. 現有 GitHub 流程更新市場資料
2. 產生最新 `mwp_a_strategy_tracking.json`
3. 網站與 nightly 報表照常部署

### 每個交易日 08:55 到 09:05

1. execution agent 同步最新 tracking JSON
2. 篩出狀態為 `待次日開盤` 的正式追蹤記錄
3. 驗證這些記錄的 next trading date 為當日
4. 等待開盤價可取得
5. 逐筆判斷：
   - `open_price <= entry_limit_price` -> `called`
   - 否則 -> `open_failed`
6. `called` 記錄：
   - 發 Telegram
   - 寫 call log
   - 若為 sandbox/live 模式則送單

### 持倉期間

1. 根據正式追蹤持倉與 agent 本地持倉帳同步狀態
2. 後續由 broker quote / WebSocket 監控出場條件
3. 若達出場條件：
   - 發通知
   - 寫交易紀錄
   - 送 sandbox/live exit order

## 與現有 repo 的邊界

保留在現有 repo：

- `build_mwp_a_strategy_tracking.py`
- `send_mwp_c_open_entry_calls.py` 的策略與訊息格式參考
- `alert_signals.py` 的 Telegram 發送能力
- 正式追蹤網站頁面

建議新增為 execution agent 專案：

- `execution_agent/`
- `execution_agent/main.py`
- `execution_agent/tracking_sync.py`
- `execution_agent/open_entry_runner.py`
- `execution_agent/quote_gateway.py`
- `execution_agent/order_adapter.py`
- `execution_agent/notifier.py`
- `execution_agent/state_store.py`
- `execution_agent/config.py`

理由：

- 避免把交易執行狀態混進靜態網站建置流程
- 降低 deployment 與 execution 互相干擾
- 未來更容易部署到 VM / container

## secrets 與安全

必須獨立管理：

- Telegram bot token
- Telegram chat id
- Broker API account / password / 憑證
- 任何 session token 或 access token

原則：

- 不進 git
- 儲存在 VM 環境變數或 GCP Secret Manager
- 啟動時注入 execution agent

## 觀測與稽核

至少要有：

- 每日 agent heartbeat
- 今日 pending count
- 今日 called count
- 今日 open_failed count
- 每筆送單結果
- 每筆 Telegram 發送結果
- 錯誤 traceback

建議：

- 本地文字 log
- SQLite 稽核表
- 後續可加上 Telegram 管理訊息或簡單 healthcheck

## 失敗處理

### tracking JSON 無法同步

- 中止交易判斷
- 發送錯誤通知
- 不使用舊資料自動下單

### 開盤價抓不到

- 記錄 `missing_open_quote`
- 重試有限次
- 超時後發送錯誤通知

### Telegram 發送失敗

- 不影響是否記錄交易判斷結果
- 需記錄通知失敗狀態

### 下單失敗

- 保留判斷結果
- 記錄 order error
- 需能區分「策略判斷成立」與「券商執行失敗」

## 分階段實作

### Phase 1

- 建立 GCP VM
- 建立 execution agent skeleton
- 讓 agent 可以同步 tracking JSON
- 把正式追蹤買進 call 從 GitHub Actions 搬到 VM
- 只做 Telegram，不下單

### Phase 2

- 接永豐沙盒下單
- 把 `called` 事件同步成 sandbox order / fill / position

### Phase 3

- 接券商 WebSocket / snapshot
- 以 broker 行情取代公開開盤資料來源

### Phase 4

- 接正式單
- 補齊持倉監控與自動出場

## 驗收標準

1. 正式追蹤買進 call 不再依賴 GitHub schedule。
2. 交易日開盤附近可準時完成 pending 名單判斷。
3. 每筆 `called` / `open_failed` 都有持久化紀錄。
4. Telegram 發送結果可追蹤。
5. sandbox 模式可與正式追蹤事件對齊。
6. 未來切 broker WebSocket 與正式單時，不需要重寫正式追蹤來源邏輯。

## 決策結論

正式追蹤買進 call 的最佳解不是本地電腦排程，也不是繼續強化 GitHub Actions，而是：

- 用 GCP Compute Engine 建立常駐 execution agent
- 保留現有 GitHub nightly data pipeline
- 讓 execution agent 專責開盤判斷、通知、下單與持倉監控

這條路徑最符合目前需求，也最接近最終的全自動券商交易架構。
