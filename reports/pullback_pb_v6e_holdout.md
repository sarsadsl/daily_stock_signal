# PB-V6E-holdout

Variant: 第20日站上MA20續抱；第20日後改用跌破MA20出場，不再用移動停利

Robust gate: FAIL
Reasons: test average worsened, test median worsened, test still has latest-close unresolved exits

| Split | Trades | PB-V4 avg | V6E avg | Delta avg | PB-V4 median | V6E median | Delta median | Latest close unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 133 | 4.51% | 6.10% | 1.59% | 2.00% | 2.00% | 0.00% | 0 |
| validation | 45 | 5.01% | 6.28% | 1.27% | -7.00% | -7.00% | 0.00% | 1 |
| test | 45 | 6.16% | 5.85% | -0.31% | 2.72% | 2.00% | -0.72% | 1 |
