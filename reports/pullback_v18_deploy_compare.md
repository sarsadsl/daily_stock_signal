# PB-V18-deploy-compare

Verdict: 不可部署；可列為 forward paper-trading 觀察候選

| Version | Full | Deterministic stock-test | Random stock-test | Add-on units | Package stock-test |
|---|---|---|---|---|---|
| V18 all-score no-limit：不加碼 | 222 份｜48.65%｜6.09%｜中位 -0.79%｜未實現 7 | - | mean 45.2 份｜50.98%｜7.09%｜pass 0/10 | - | - |
| V18 all-score no-limit：V23 加碼 | 678 份｜56.78%｜25.12%｜中位 1.28%｜未實現 334 | 114 份｜52.63%｜9.83%｜中位 1.15%｜未實現 59 | mean 137.4 份｜57.13%｜24.42%｜pass 5/10 | 456 份｜60.75%｜34.39%｜中位 9.41%｜未實現 327 | 39 組｜46.15%｜5.32%｜中位 -0.52% |

## Blockers
- Deterministic stock-test does not clear 60% win / 10% average return.
- Random stock-test pass count is only 5/10, not stable enough.
- Unresolved exposure is very high; many gains are latest-close estimates, not realized exits.
- Package stock-test is weak, meaning original signal quality is not strong enough even if add-ons lift unit returns.
- Mother pool without add-ons is weak; deployment depends heavily on add-on winners.

## Positives
- Full average return clears 10% after V23 add-ons.
- Add-on units capture large-wave upside and show high average return.
- Random stock-test average return clears 10% in mean and all 10 seeds clear avg>=10.
