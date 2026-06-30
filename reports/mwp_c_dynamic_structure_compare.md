# MWP-C 動態結構低點比較

- Pivot 定義：左右各 2/2 根 K 確認的局部低點。
- 第三版動態啟動門檻：浮盈達 15% 後才開始上移結構低點。

## 整體結果
### 固定 structure_low（現行版）
- 說明：結構低點固定鎖在訊號日至確認K區間最低 low，不會隨後續上漲而上移。
- Full units：245｜勝 42.86%｜均 40.44%｜中 -5.19%｜損益 +9,908,940｜未 109
- Base units：179｜勝 36.31%｜均 39.95%｜中 -7.00%｜損益 +7,151,250｜未 62
- Add-on units：66｜勝 60.61%｜均 41.78%｜中 7.95%｜損益 +2,757,690｜未 47
- Random unit stock-test：test均 49｜勝均 45.31%｜報酬均 47.07%｜p25 39.15%
- 動態更新單位：0，抬高結構低點單位：0
- 出場組成：{"structure_break": 24, "latest_close_unresolved": 109, "catastrophic_close_stop": 9, "hard_stop": 103}

### pivot swing low 動態上移
- 說明：用左右各 2 根 K 確認的局部低點作為新的 swing low，只允許 structure_low 往上抬高，不往下降。
- Full units：232｜勝 42.24%｜均 17.69%｜中 -2.42%｜損益 +4,103,520｜未 26
- Base units：182｜勝 41.76%｜均 18.97%｜中 -7.00%｜損益 +3,452,020｜未 16
- Add-on units：50｜勝 44.00%｜均 13.03%｜中 -0.61%｜損益 +651,500｜未 10
- Random unit stock-test：test均 46｜勝均 43.85%｜報酬均 26.15%｜p25 18.44%
- 動態更新單位：128，抬高結構低點單位：128
- 出場組成：{"structure_break": 115, "hard_stop": 91, "latest_close_unresolved": 26}

### 浮盈達 15% 後才啟用 pivot swing low
- 說明：前段先保留原始結構空間，等單位曾出現至少 15% 浮盈後，才開始用 pivot swing low 抬高 structure_low。
- Full units：233｜勝 42.49%｜均 19.52%｜中 -2.82%｜損益 +4,549,000｜未 32
- Base units：182｜勝 40.66%｜均 20.24%｜中 -7.00%｜損益 +3,683,630｜未 19
- Add-on units：51｜勝 49.02%｜均 16.97%｜中 -0.14%｜損益 +865,370｜未 13
- Random unit stock-test：test均 46｜勝均 44.59%｜報酬均 28.02%｜p25 18.02%
- 動態更新單位：111，抬高結構低點單位：111
- 出場組成：{"structure_break": 109, "hard_stop": 92, "latest_close_unresolved": 32}

## 相對固定版差異
### pivot swing low 動態上移
- Units 差：-13
- Full 平均差：-22.75%
- Full 勝率差：-0.62%
- 總損益差：-5,805,420
- Random 平均差：-20.92%
- Random p25 差：-20.71%
- 被改寫單位：113，改善 49，惡化 56，合計損益差 -5,166,150

### 浮盈達 15% 後才啟用 pivot swing low
- Units 差：-12
- Full 平均差：-20.92%
- Full 勝率差：-0.37%
- 總損益差：-5,359,940
- Random 平均差：-19.05%
- Random p25 差：-21.13%
- 被改寫單位：107，改善 40，惡化 51，合計損益差 -4,828,750
