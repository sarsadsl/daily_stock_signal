# MWP-C 永豐 Sandbox Execution Adapter 設計

日期：2026-07-10

## 目標

建立 MWP-C execution agent 的 Phase 2：當 Phase 1 已經判斷出正式追蹤 `called` 事件時，將該事件同步成永豐 Shioaji sandbox 委託、成交紀錄與模擬部位。

這一階段的核心目的不是正式自動下單，而是建立一個可稽核、可回放、可每天觀察的模擬下單帳本，讓正式追蹤的買進 call 能和券商 sandbox 行為對齊。

## 不做的事

- 不送正式單。
- 不修改 `reports/mwp_a_strategy_tracking.json` 的正式追蹤判斷。
- 不修改現有網頁正式追蹤顯示邏輯。
- 不自行重新判斷進出場條件；進場只吃 Phase 1 `called` 決策。
- 不在 git、報告或 log 內輸出 API key、secret、session token、帳號或憑證內容。

## 現況

Phase 1 已具備：

- 從 `tracking.formal_forward_records` 選出待次日開盤候選。
- 以現有 next-trading-date 語意對齊正式追蹤。
- 抓取開盤價並產生 `called` / `open_failed` 決策。
- dry-run 模式不寫 DB、不發 Telegram。
- live-run 模式在 Telegram 成功後才寫 SQLite 去重紀錄。

2026-07-10 模擬結果：

- Shioaji `simulation=True` login/logout 成功。
- 現有 branch 尚未接 broker order adapter。
- 2026-07-09 回放中，31 筆候選有 2 筆 `called`：`3094 聯傑`、`3090 日電貿`。

## 安全原則

### Sandbox-only 預設

新增下單相關設定時，預設必須是安全狀態：

- `BROKER_MODE=noop`：預設，不送任何 broker order。
- `BROKER_MODE=sandbox`：只送 Shioaji simulation order。
- `BROKER_MODE=live`：此階段不支援，若被設定應直接拒絕啟動。
- `SANDBOX_ONLY=1`：Phase 2 必須存在且必須為 `1`，否則拒絕送單。

### 送單條件

只有同時符合以下條件才可送 sandbox order：

- Phase 1 decision result 是 `called`。
- 該 `call_key` 尚未被 sandbox ledger 標記為已處理。
- broker 設定為 `BROKER_MODE=sandbox`。
- `SANDBOX_ONLY=1`。
- Shioaji sandbox login 成功。
- order payload 通過本地風控檢查。

`open_failed`、`missing_open_quote`、`skipped_already_processed` 一律不可送單，只能記錄 audit。

## 模組設計

### `execution_agent.broker_config`

負責讀取 broker 相關設定。

建議環境變數：

- `BROKER_MODE`：`noop` 或 `sandbox`。
- `SANDBOX_ONLY`：Phase 2 必須為 `1`。
- `SHIOAJI_API_KEY`：永豐 API key。
- `SHIOAJI_SECRET_KEY`：永豐 secret key。
- `ORDER_CASH_PER_TRADE`：每筆模擬下單金額，預設 `100000`。
- `ORDER_LOT_MODE`：預設 `odd_lot_or_round_down`，避免股數超過預算。

驗證規則：

- `BROKER_MODE` 未設定時視為 `noop`。
- `BROKER_MODE=sandbox` 時必須同時存在 Shioaji key / secret。
- `BROKER_MODE=live` 必須丟出錯誤，避免誤送正式單。

### `execution_agent.broker_adapter`

定義 broker 介面與 Shioaji sandbox 實作。

核心介面：

```python
class BrokerAdapter:
    def submit_buy_order(self, request: SandboxOrderRequest) -> SandboxOrderResult:
        ...
```

資料模型：

- `SandboxOrderRequest`
  - `call_key`
  - `market`
  - `stock_no`
  - `stock_name`
  - `signal_date`
  - `open_price`
  - `entry_limit_price`
  - `cash_budget`
  - `quantity`
  - `price`
  - `order_type`
- `SandboxOrderResult`
  - `call_key`
  - `accepted`
  - `broker_order_id`
  - `submitted_at`
  - `message`

Phase 2 初版只需要買進委託，出場與持倉監控留到 Phase 3。

### `execution_agent.order_sizing`

負責把 `called` 決策轉成 sandbox order payload。

初版規則：

- 每筆以 `ORDER_CASH_PER_TRADE` 為預算。
- 委託價格使用 `open_price` 或最接近 Shioaji sandbox 支援的限價欄位。
- 股數用 `cash_budget / open_price` 向下取整。
- 若股數低於最小可下單單位，記錄 `sizing_rejected`，不送單。
- 初版不做加碼、資金佔用或最大持股數限制；這些留到自動化下單前的風控階段。

### `execution_agent.sandbox_ledger`

用 SQLite 記錄 sandbox 委託與模擬部位。它和 Phase 1 call log 可以共用同一個 DB 檔，但使用獨立資料表，避免語意混在一起。

建議資料表：

#### `sandbox_orders`

- `id`
- `call_key`
- `market`
- `stock_no`
- `stock_name`
- `signal_date`
- `open_price`
- `entry_limit_price`
- `cash_budget`
- `quantity`
- `price`
- `order_type`
- `broker_order_id`
- `status`
- `message`
- `created_at`

`call_key` 必須唯一，確保同一個正式追蹤事件不會重複送 sandbox order。

#### `sandbox_positions`

- `id`
- `call_key`
- `market`
- `stock_no`
- `stock_name`
- `entry_date`
- `entry_price`
- `quantity`
- `status`
- `created_at`
- `updated_at`

Phase 2 可以先把成功送出的 sandbox order 視為模擬持倉建立事件；若 Shioaji sandbox 回傳更精確成交資訊，則優先採用 broker 回傳值。

#### `sandbox_events`

- `id`
- `call_key`
- `event_type`
- `message`
- `created_at`

用來記錄 login failure、sizing rejection、broker exception、duplicate skip 等稽核事件。

## Runner 串接

Phase 1 的 `run_open_entry_cycle(...)` 目前負責 decision、Telegram、state log。Phase 2 不應把 broker 細節塞進 decision core，而是新增一層 execution flow：

1. Phase 1 產生 `OpenEntryDecision`。
2. 若 `decision.result != "called"`，只記錄 audit，不送 broker。
3. 若 `decision.result == "called"`，交給 sandbox executor。
4. sandbox executor 檢查 ledger 是否已處理 `call_key`。
5. sizing 成功後送 Shioaji sandbox order。
6. broker 成功回覆後寫入 `sandbox_orders` 與 `sandbox_positions`。
7. broker 失敗時寫入 `sandbox_events`，不標記為已完成，以便下次可重試。

這樣可以保留 Phase 1 的正式追蹤判斷，不讓 broker 下單失敗反過來改變正式追蹤狀態。

## Telegram 與報告

Phase 2 不改現有 Telegram call 文案。新增 sandbox order 後，可以先只寫本地 ledger，不額外傳 Telegram，避免訊息太多。

若後續需要通知，建議新增獨立通知類型：

- sandbox order accepted
- sandbox order rejected
- sandbox duplicate skipped

這些不應混入正式買進 call 訊息。

## 錯誤處理

### Shioaji login 失敗

- 記錄 `sandbox_events`。
- 不送單。
- runner exit code 可維持非零，方便排程或 VM log 偵測。

### order sizing 失敗

- 記錄 `sizing_rejected`。
- 不送單。
- 不標記為 sandbox order completed。

### broker submit 失敗

- 記錄 exception 類型與安全訊息。
- 不記錄 secret。
- 不建立 position。
- 不標記 call_key 為已處理，保留重試可能。

### 重複執行

- 若 `sandbox_orders.call_key` 已存在且狀態為 accepted / filled / simulated_filled，直接 skip。
- skip 事件可記錄到 `sandbox_events`，但不可再次送單。

## 測試策略

### 單元測試

- broker config：
  - 預設 `BROKER_MODE=noop`。
  - `BROKER_MODE=live` 直接拒絕。
  - sandbox mode 缺 key / secret 會拒絕。
- order sizing：
  - 用 open price 計算股數。
  - 預算不足時拒絕。
  - 股數不超過預算。
- sandbox ledger：
  - `call_key` 唯一。
  - 成功 order 會建立 position。
  - broker 失敗不建立 position。
- sandbox executor：
  - 只處理 `called`。
  - `open_failed` 不送 broker。
  - duplicate call 不重送。
  - broker failure 可重試。

### 整合測試

使用 fake broker client，不連 Shioaji：

- 用 2026-07-09 的兩筆 `called` 決策建立 fake orders。
- 驗證 ledger 中有 2 筆 sandbox orders 和 2 筆 positions。
- 第二次執行同一批決策時不新增 order。

### 手動測試

使用真 Shioaji sandbox：

1. `.env` 放 `SHIOAJI_API_KEY` 與 `SHIOAJI_SECRET_KEY`。
2. `BROKER_MODE=sandbox`。
3. `SANDBOX_ONLY=1`。
4. 使用受控的 historical decision fixture 測一筆 sandbox order。
5. 檢查 SQLite ledger，而不是只看終端輸出。

## 成功標準

- 不設定 broker 時，現有 Phase 1 runner 行為不變。
- 設定 `BROKER_MODE=sandbox` 後，`called` 決策會送出 sandbox order。
- 同一個 `call_key` 重跑不會重複送單。
- Shioaji key / secret 不會出現在 log、測試輸出、報告或 git diff。
- sandbox order 與 position 可從 SQLite 查詢。
- 所有測試通過。

## 下一階段

Phase 2 完成後，才進入 Phase 3：

- 用 broker quote / WebSocket 監控持倉。
- 將正式追蹤出場事件同步成 sandbox exit order。
- 建立未實現損益與已實現損益的 sandbox 專屬報表。

正式 live order 必須另開獨立設計，不應從 Phase 2 直接開關切換。
