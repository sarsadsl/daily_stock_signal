# MWP-C-return-first-capped-ma20-slope

策略：MWP-C 報酬率優先低頻加碼策略
正式濾網：MA20 近 5 日斜率 > 0

## 結果
- Full units: 285｜勝 43.51%｜均 39.92%｜中 -6.18%｜未 125
- Base units: 212｜勝 36.32%｜均 38.73%｜中 -7.00%｜未 74
- Add-on units: 73｜勝 64.38%｜均 43.38%｜中 14.73%｜未 51
- Random unit stock-test: test均 56.8｜報酬均 50.65%｜p25 41.21%｜勝均 46.64%
- Random package stock-test: test均 42.7｜報酬均 41.47%｜p25 31.57%｜勝均 39.62%
- Lifecycle violations: 0

## Baseline comparison
- Baseline full units: 299｜勝 43.14%｜均 39.27%｜中 -6.87%｜未 130
- Baseline random unit stock-test: test均 57.8｜報酬均 33.50%｜p25 29.13%｜勝均 40.63%

## Rules
- PB-V23 original mother pool
- Max 1 add-on per mother lifecycle; MA20 retest band 1.9%; add-ons only while mother is open; 10-trading-day same-stock buy/buy-signal cooldown; add-ons sync-exit when mother exits.
- Mother hard stop 7%; add-on close-based catastrophic stop 15%; mother exit synchronizes remaining add-ons.
