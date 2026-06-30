# MWP-C-return-first-capped-ma20-slope-consolidation30

策略：MWP-C 報酬率優先低頻加碼策略
正式濾網：MA20 近 5 日斜率 > 0，且母單採 30 日整理低點保護，突破條件用盤中高點，不套用到加碼單

## 結果
- Full units: 245｜勝 40.41%｜均 34.49%｜中 -4.93%｜未 103
- Base units: 179｜勝 36.87%｜均 34.83%｜中 -7.00%｜未 59
- Add-on units: 66｜勝 50.00%｜均 33.56%｜中 0.12%｜未 44
- Random unit stock-test: test均 48.9｜報酬均 41.07%｜p25 34.19%｜勝均 43.00%
- Random package stock-test: test均 35.8｜報酬均 34.02%｜p25 24.49%｜勝均 38.07%
- Lifecycle violations: 0

## Baseline comparison
- Baseline full units: 259｜勝 40.15%｜均 33.75%｜中 -5.82%｜未 108
- Baseline random unit stock-test: test均 51.6｜報酬均 29.02%｜p25 25.80%｜勝均 39.97%

## Rules
- 母單來源先從主升段回檔訊號中，保留次日開盤低於訊號日收盤 2% 的候選，再交給 MWP-C 正式篩選。
- 每個母單生命週期最多 1 筆加碼；加碼需回測 MA20 1.9% 範圍內；母單仍持有中才可加碼；同股 10 個交易日內若已有買進或買進候選則不加碼；母單出場時加碼單同步出場。
- Mother hard stop 7%; mother structure floor ratchets upward only after breaking the prior 30-day range high; add-on close-based catastrophic stop 15%; mother exit synchronizes remaining add-ons.
