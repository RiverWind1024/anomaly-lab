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
data/annotations/<series_id>.jsonl        # 全部 —— 基准集与生产检测记录都是它
data/annotations/run-<run_id>/<series_id>.jsonl        # 旧格式，读取时仍兼容
```

每行：

```json
{"series_id":"s1","start":"2026-10-29T03:00:00","end":"2026-10-29T04:00:00","type":"spike","created_at":"2026-10-29T03:00:00+00:00"}
```

⚠️ **区间存时间戳，不存数组下标**：

- 下标只在「序列永远不变」时成立 —— 生产任务是**滚动窗口**，
  同一个下标在不同 run 里指向完全不同的时刻，标注会整段错位；
- 时间戳与序列时间轴同源（naive ISO，秒精度），换算零歧义。

⚠️ **标注按「序列 + 时间区间」存，不按运行** ——
真值是**数据的属性**，不是某次运行的属性。

生产任务是滚动窗口，同一个异常会被连续几十次运行反复报出。
如果标注绑 run，用户就得把同一段异常标几十次，标注预算全浪费在重复劳动上。
时间区间本身就是定位（`start` / `end`），run 只是「看哪次波形」的入口：
**标注一次，所有时间轴覆盖该时段的检测记录都复用它。**

⚠️ 读取时会**合并旧格式**（`run-*/` 目录）—— 老数据不用迁移也能继续算。

⚠️ **老的异常标注没有伴随的 `reviewed` 记录** ——
评估退化成「只在标注区间内计分」（保守口径：没看过的地方不判误报）。

区间是**闭区间** `[start, end]` —— 与切窗的「左闭右开」不是一回事。

⚠️ 生产数据的标注还带两个字段：

```json
{"series_id":"s1","start":"...","end":"...","type":"spike",
 "run_id":9320,"rate":0.2,"layer_size":9022}
```

⚠️ **还有第二种标注：整条记录核对过**（`type="reviewed"`，**没有** `start`/`end`）：

```json
{"series_id":"s1","type":"reviewed","run_id":9320,"rate":0.2}
```

- 语义 = 「这次运行的整个窗口我看过了」；窗口从 `run_series` 的时间范围取；
- 标注页点「这条记录正常」就写这一条，**不用画区间**；
- 保存异常区间时也会自动带上它（画了标注 = 看了整条波形）。

⚠️ **它是负样本标签，也是覆盖率声明**：
没有它，评估只能把「没标的地方」当正常 ——
一条 6 分钟的标注会让同一窗口里其余几十个告警点**凭空变成误报**。

- `run_id` = 标它时看的是哪次运行（**只做溯源**，不影响存储路径）；
- `rate` = 标这条时它所在层的**采样率**；
- `layer_size` = 该层的候选总量。

⚠️ 这两个字段是**分层抽样反算的依据**：一条记录在 20% 采样率下被抽中，
就代表总体里的 5 条（权重 = 1 / 0.2）。
采样率后来变了，老标注仍按它当初的权重算 ——
它是从那个样本框里抽出来的，代表的框没变。

⚠️ **层是「数据源 → 指标 → 检出结果」** —— 报出了告警的记录是「异常」层，
什么都没报的是「正常」层，**两层的采样率不一样**
（正常记录远多于异常记录，默认 50% / 5%）。
`rate` 记的是它自己那一层的那个采样率。

## 合规

`compliance-check` 扫描 `README.md`、`src/`、`tests/`、`notebooks/`、`docs/`；讨论禁词本身的 `docs/DESIGN.md`、`docs/PLAN.md`、`docs/RESEARCH.md` 与禁词表文件豁免。项目只允许合成数据、公开数据集与公开实现。
