# 数据说明

## 合成数据（默认）

`generate_series(metric_class, n, seed, n_anomalies, anomaly_types)` 生成一条 `SeriesBundle`：

- 6 种形态：`stationary`、`periodic`、`trending`、`step`、`high_zero_ratio`、`sparse_event`
- 6 种异常：`spike`、`contextual`、`drift`、`freq_shift`、`variance_shift`、`flatline`
- 长异常长度 10–20 点，尖峰 1–3 点；标注占比控制在 15% 以内
- `labels` 为 `int8` 逐点真值；`meta` 记录形态、异常类型与区间、生成参数
- 所有随机性由 `seed` 驱动，可复现

落盘结构：

```
data/synthetic/
  index.json          # 序列清单与元信息
  <series_id>.npz     # values / timestamps / labels / meta
```

## 公开数据（UCR）

```bash
# 离线模式：只读缓存，缺失直接报错
ANOMALY_LAB_OFFLINE=1 python -m anomaly_lab.cli classify

# 在线模式需要显式 URL 模板（UCR 单序列 URL 尚未校准）
export ANOMALY_LAB_UCR_SERIES_URL='https://example.org/ucr/{name}.txt'
```

缓存位于 `data/cache/public/<name>/`，包含 `values.txt` 与 `meta.json`（`freq`、`anomaly_intervals`、来源、sha256）。下载支持 Range 断点续传。

公开集只用于泛化验证，不参与阈值/参数选择。

## 人工标注

Web 标注页把刷选结果追加到：

```
data/annotations/<series_id>.jsonl
```

每行：

```json
{"series_id":"s1","start":10,"end":12,"type":"spike","created_at":"2026-10-29T03:00:00+00:00"}
```

## 合规

`compliance-check` 扫描 `README.md`、`src/`、`tests/`、`notebooks/`、`docs/`；讨论禁词本身的 `docs/DESIGN.md`、`docs/PLAN.md`、`docs/RESEARCH.md` 与禁词表文件豁免。项目只允许合成数据、公开数据集与公开实现。
