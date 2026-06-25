# MWP-C-return-first-capped-ma20-slope

策略：MWP-C 報酬率優先低頻加碼策略
正式濾網：MA20 近 5 日斜率 > 0

## 結果
- Full units: 243｜勝 43.21%｜均 40.02%｜中 -5.80%｜未 107
- Base units: 179｜勝 36.31%｜均 39.60%｜中 -7.00%｜未 62
- Add-on units: 64｜勝 62.50%｜均 41.19%｜中 11.74%｜未 45
- Random unit stock-test: test均 48.5｜報酬均 46.80%｜p25 39.76%｜勝均 45.92%
- Random package stock-test: test均 35.8｜報酬均 39.33%｜p25 29.02%｜勝均 38.95%
- Lifecycle violations: 0

## Baseline comparison
- Baseline full units: 257｜勝 42.80%｜均 39.24%｜中 -6.18%｜未 112
- Baseline random unit stock-test: test均 50.9｜報酬均 33.02%｜p25 29.12%｜勝均 40.69%

## Rules
- PB-V23 original mother pool
- Max 1 add-on per mother lifecycle; MA20 retest band 1.9%; add-ons only while mother is open; 10-trading-day same-stock buy/buy-signal cooldown; add-ons sync-exit when mother exits.
- Mother hard stop 7%; add-on close-based catastrophic stop 15%; mother exit synchronizes remaining add-ons.
