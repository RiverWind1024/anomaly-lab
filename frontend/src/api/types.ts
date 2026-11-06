/**
 * 后端 API 的手写类型。
 *
 * ⚠️ **字段名不许改** —— 全部照后端实际响应逐字段核对（2026-10-30 实测）。
 *    后端改字段时这里必须同步改，否则运行期才发现，代价很高。
 *
 * 核对来源：
 *   - /api/platform/* → 运行中的后端实测响应
 *   - /api/summary、/api/badcases、/api/annotate → 端点源码 + 实测
 *   - 评估 rows/summary → reports/latest/report.json
 */

// ─────────────────────────────────────────── /api/platform/catalog

/**
 * 数据源的「kind 专属配置」。
 *
 * ⚠️ **凭据字段（headers / body / url 里的密钥）后端会脱敏** ——
 *    前端拿到的是 `••••` 这类哨兵值，**原样回传**后端会还原真值。
 * ⚠️ **config 是「整体替换」语义** —— 前端必须提交**完整**的 config，
 *    没传的顶层键会被后端删掉。
 */
export interface SourceConfig {
  /** kind=http 时的请求 URL 模板，{sql} 是占位符 */
  url?: string
  method?: 'GET' | 'POST'
  body?: Record<string, unknown>
  headers?: Record<string, string>
  format?: 'json' | 'csv' | 'jsonl'
  rows_path?: string
  timeout_seconds?: number
}

export interface CatalogSource {
  id: number
  name: string
  kind: string
  path: string
  created_at: string
  /**
   * kind 专属配置（凭据已脱敏）。
   *
   * ⚠️ 可选 —— 既有测试里的 fixture 没这个字段，改成必填会一片红。
   */
  config?: SourceConfig
}

export interface CatalogMetric {
  id: number
  source_id: number
  name: string
  query: string
  time_column: string
  value_column: string
  group_column: string | null
  time_format: string
  freq: string
  source_timezone: string
  missing_policy: string
  created_at: string
}

export interface CatalogJob {
  id: number
  metric_id: number
  name: string
  detector: string
  alert_threshold: number
  critical_threshold: number
  window_points: number
  interval_seconds: number
  enabled: boolean
  last_run_at: string | null
  next_run_at: string | null
  created_at: string
  alert_rules: AlertRule[]
}

export interface CatalogDetector {
  name: string
  default_threshold: number
  score_type: string
  label: string
  /**
   * 当前环境能不能用。
   *
   * 只有 Chronos 会是 false —— 它需要可选依赖 + 本地权重缓存。
   * 后端从 `detector_available()` 取，字段缺失时按「可用」处理（兼容旧后端）。
   */
  available?: boolean
  /** 不可用的原因（人话，直接显示给用户）。 */
  reason?: string | null
  /** 慢算法（秒级/序列）—— 定时任务要留足间隔。 */
  slow?: boolean
}

export interface Catalog {
  sources: CatalogSource[]
  metrics: CatalogMetric[]
  jobs: CatalogJob[]
  detectors: CatalogDetector[]
}

// ─────────────────────────────────── 数据浏览 /api/platform/sources/{id}/query

/** 浏览结果的一列。`type` 是后端按 dtype 推断的类型名。 */
export interface SourceQueryColumn {
  name: string
  type: string
}

/** 一次浏览的结果 —— 列结构 + 前 N 行。 */
export interface SourceQueryResult {
  columns: SourceQueryColumn[]
  /** 行是**数组**（不是对象）—— 列名在 columns 里。 */
  rows: unknown[][]
  /**
   * 时间轴坐标 —— `time_column` 那一列解析成的 **epoch 毫秒**。
   *
   * ⚠️ `null` = 没有时间列（或那一列不在结果里）→ 不画时序图。
   * ⚠️ 元素里的 `null` = **这一行的时间解析不出来**（断点）。
   *    绝不能拿 0 顶替 —— 那会画到 1970 年，看着像「数据都在 1970 年」。
   * ⚠️ 后端用**与指标运行时同一份**逻辑解析 —— 浏览画的图必须等于跑出来的。
   */
  time_values: (number | null)[] | null
  /**
   * 本次取到的**行数**（≤ limit）。
   *
   * ⚠️ **不是**结果集的真实总行数 —— limit 已下推到 SQL，
   *    平台根本没看到更多的行。
   */
  total: number
  /** 还有更多行没取到（本次取到的行数已经撞到 limit）。 */
  truncated: boolean
  elapsed_ms: number
}

// ─────────────────────────────────────────── 告警记录 /api/platform/alerts

/**
 * 一条告警事件 = 一段连续告警点合并成的区间。
 *
 * ⚠️ `level` 是**档位名**，来自任务的规则表，不一定是 P0/P1（可自定义如「注意」）。
 *    `level_index` 才是严重度序（越大越严重）—— 排序、筛选用它。
 */
export interface AlertEvent {
  job_id: number
  job_name: string
  metric_id: number
  metric_name: string
  series_id: string
  group: string | null
  level: string
  level_index: number
  start_ts: string
  end_ts: string
  n_points: number
  max_score: number
  detector: string
  score_type: string
  run_id: number
}

/** 没被纳入统计的任务 —— 必须说清为什么，不能静默消失。 */
export interface SkippedJob {
  job_id: number
  name: string
  reason: string
}

// ─────────────────────────────────────────── 概览 /api/platform/overview

export interface OverviewCounts {
  sources: number
  metrics: number
  jobs: number
  enabled_jobs: number
}

export interface OverviewRuns {
  total: number
  success: number
  failed: number
  running: number
}

export interface OverviewLatestRun {
  id: number
  status: string
  started_at: string
  finished_at: string | null
  n_series: number
  n_alerts: number
  error: string | null
}

export interface OverviewJob {
  id: number
  name: string
  enabled: boolean
  detector: string
  metric_id: number
  last_run: OverviewLatestRun | null
}

export interface Overview {
  counts: OverviewCounts
  runs: OverviewRuns
  alerts: {
    total: number
    by_level: Array<{ level: string; count: number }>
    by_job: Array<{ job_id: number; job_name: string; count: number }>
    top_series: Array<{ series_id: string; count: number }>
    /** 没纳入统计的任务数（没跑过 / 失败 / 运行中）。 */
    skipped: number
  }
  feedback: {
    total: number
    by_kind: Array<{ kind: string; count: number }>
  }
  jobs: OverviewJob[]
}

// ─────────────────────────────────────────── 存储与保留 /api/platform/storage

/** 保留策略 —— 只有一个维度：保留多少天。 */
export interface RetentionPolicyInfo {
  retention_days: number
}

export interface StorageUsage {
  policy: RetentionPolicyInfo
  runs: {
    /** 保留中的运行记录数。 */
    kept: number
    /** 结果目录数。 */
    n_dirs: number
    /** 结果目录占用的字节数。 */
    bytes: number
  }
  database: {
    path: string
    bytes: number
  }
  feedback: {
    total: number
  }
  /** 上次清理时间；还没清过是 null。 */
  last_pruned_at: string | null
  last_pruned: {
    deleted_runs: number
    freed_bytes: number
  }
}

/** 一次清理的结果。 */
export interface PruneResult {
  deleted_runs: number
  deleted_dirs: number
  orphan_dirs: number
  freed_bytes: number
  kept_runs: number
  dry_run: boolean
  /**
   * 触发了磁盘上限兜底的任务 —— 它们的实际保留期比配置的短。
   *
   * ⚠️ 保留期永远优先，但任务频率太高时磁盘会撑不住，
   *    这时候宁可少留也不能让平台崩掉。触发了要让人知道。
   */
  disk_capped_jobs: number[]
  /** 清理后的最新占用 —— 少发一次请求。 */
  storage?: StorageUsage
}

export interface AlertListResponse {
  events: AlertEvent[]
  levels: string[]
  /** 序列候选 —— 来自**未筛选**的集合，否则筛选器会把自己锁死。 */
  series: string[]
  jobs: { id: number; name: string }[]
  skipped: SkippedJob[]
}

// ─────────────────────────────────────────── 告警规则

/** 一条告警规则。倍数条件与绝对值条件二选一 —— 后端 `AlertRule.as_dict()` 按 is_absolute 分支。 */
export interface AlertRule {
  /** 倍数条件（缩放因子）。绝对值规则里没有这个键。 */
  multiplier?: number
  /** 绝对值条件：> >= < <= */
  op?: string
  /** 绝对值条件的阈值。 */
  value?: number
  /** 档位名：正常 / P1 / P0 */
  level: string
}

// ─────────────────────────────────────────── 运行记录

export type RunStatus = 'running' | 'success' | 'failed' | 'insufficient_data'

export interface RunSummary {
  id: number
  job_id: number
  status: RunStatus
  n_series: number
  n_alerts: number
  error: string | null
  started_at: string
  finished_at: string | null
}

export interface RunList {
  runs: RunSummary[]
}

// ─────────────────────────────────────────── 预览 /api/platform/jobs/{id}/preview

export interface SeriesEntry {
  series_id: string
  group: string | null
  n: number
  n_valid: number
  n_missing: number
  n_alerts: number
  n_p0: number
  sufficient: boolean
  detector: string
  metric_class: string | null
  fallback: boolean
  /** 尺度来源（iqr / mad / std / none）；老产物没有这个键。 */
  scale_source?: string
  /** 尺度是否可用；老产物没有这个键。 */
  status?: 'ok' | 'undetermined'
  /** 尺度是否降级过；老产物没有这个键。 */
  scale_fallback?: boolean
  file: string | null
}

export interface Preview {
  run_id: number
  job_id: number
  detector: string
  requested_detector: string
  /**
   * ⚠️ 是 `string`，**不是 null**：
   *   - 数据不足时后端返回空串 `""`（走 `preview` 的「数据不足」分支）
   *   - 正常时是形态分类名（periodic / trend / ...）
   * 空串即代表「给不出形态」。
   */
  metric_class: string
  detector_rationale: string
  detector_fallback: boolean
  score_type: string
  /** 尺度来源（iqr / mad / std / none）；数据不足时为空串。 */
  scale_source: string
  /** 尺度是否可用；数据不足时按 ok 返回（前端先看 sufficient）。 */
  status: 'ok' | 'undetermined'
  /** 尺度是否降级过（实际来源 ≠ 检测器首选）。 */
  scale_fallback: boolean
  series_id: string
  group: string | null
  n: number
  n_valid: number
  n_missing: number
  n_alerts: number
  n_p0: number
  sufficient: boolean
  insufficient_reason: string
  sampled: boolean
  original_n: number
  timestamps: string[]
  values: (number | null)[]
  scores: (number | null)[]
  baseline: (number | null)[] | null
  lower: (number | null)[] | null
  upper: (number | null)[] | null
  severity: number[]
  alert_threshold: number
  critical_threshold: number
  alert_rules: AlertRule[]
  levels: string[]
  series: SeriesEntry[]
}

// ─────────────────────────────────────────── 多算法对比 /api/platform/jobs/{id}/compare

export interface CompareDetector {
  name: string
  score_type: string
  default_threshold: number
  baseline: (number | null)[] | null
  lower: (number | null)[] | null
  upper: (number | null)[] | null
  scores: (number | null)[]
  severity: number[]
  n_alerts: number
  /**
   * 最高档上的告警**点数**（不是档位序号）：n_top = (severity == top_level).sum()
   * 展示时必须写清是「点数」，否则会被读成「档位序号」。
   */
  n_top: number
  is_auto: boolean
}

export interface Compare {
  job_id: number
  series_id: string
  group: string | null
  n: number
  sampled: boolean
  original_n: number
  timestamps: string[]
  values: (number | null)[]
  /** ⚠️ 可为 null：分类器对点数不足的序列给不出形态。 */
  metric_class: string | null
  /** ⚠️ 可为 null：点数不足 30 时给不出置信度。 */
  confidence: number | null
  reasons: string[]
  recommendation: { detectors: string[]; rationale: string }
  auto_detector: string
  auto_fallback: boolean
  auto_rationale: string
  available: string[]
  /** 被跳过的算法（当前环境不可用，如缺 chronos 依赖）—— 附人话原因。 */
  skipped?: { name: string; reason: string }[]
  detectors: CompareDetector[]
  levels: string[]
  alert_rules: AlertRule[]
  band_width: number
}

// ─────────────────────────────────── 试跑 /api/platform/jobs/{id}/test-run

/**
 * 一次试跑的结果。
 *
 * ⚠️ **不落库** —— 没有 run_id，也没有写结果文件。
 *    但它**就是**真跑一次会得到的结果（后端走同一段执行代码）。
 */
export interface TestRunResult {
  job_id: number
  /** 实际用的检测器（auto 会落到具体算法上）。 */
  detector: string
  /** 任务里配的检测器（可能是 "auto"）。 */
  requested_detector: string
  metric_class: string
  detector_rationale: string
  detector_fallback: boolean
  score_type: string
  n_series: number
  /** 告警点数合计。 */
  n_alerts: number
  /** 最高档（P0）告警点数合计。 */
  n_p0: number
  /** 数据不足的序列数。 */
  n_insufficient: number
  alert_threshold: number
  critical_threshold: number
  alert_rules: AlertRule[]
  /** 档位名（["正常", "P1", "P0"]）。 */
  levels: string[]
  /** 每条序列的概要。 */
  series: SeriesEntry[]
  /** 每条序列的完整检测结果 —— 前端画图用。 */
  results: TestRunSeries[]
  /** 告警点逐个列出 —— **不抽样**（抽样可能正好丢掉告警点）。 */
  alerts: TestRunAlert[]
}

/** 试跑里一条序列的完整结果。 */
export interface TestRunSeries {
  series_id: string
  group: string | null
  sufficient: boolean
  insufficient_reason: string
  n: number
  n_valid: number
  n_missing: number
  n_alerts: number
  n_p0: number
  timestamps: string[]
  values: (number | null)[]
  scores: (number | null)[]
  baseline: (number | null)[] | null
  lower: (number | null)[] | null
  upper: (number | null)[] | null
  severity: number[]
}

/** 试跑里的一个告警点。 */
export interface TestRunAlert {
  series_id: string
  group: string | null
  /** 在该序列中的点序号。 */
  index: number
  timestamp: string
  value: number
  score: number
  /** 严重度序号（1 = P1，2 = P0）。 */
  severity: number
  /** 档位名。 */
  level: string
}

// ─────────────────────────────────────────── 反馈 /api/platform/feedback

export type FeedbackKind = 'correct' | 'false_alarm' | 'missed' | 'other'

/** 注意字段是 start_ts / end_ts，不是 start / end。 */
export interface FeedbackRecord {
  id: number
  job_id: number
  run_id: number | null
  series_id: string
  start_ts: string
  end_ts: string
  kind: FeedbackKind
  note: string
  created_at: string
}

export interface FeedbackList {
  feedback: FeedbackRecord[]
}

export interface FeedbackIn {
  job_id: number
  series_id: string
  start_ts: string
  end_ts: string
  kind: FeedbackKind
  note?: string
  run_id?: number | null
}

// ─────────────────────────────────────────── 调参建议 /api/platform/jobs/{id}/feedback/suggestion

/** 某个告警倍数下的表现。缺正例/负例时对应指标是 `null`（不是 1.0）。 */
export interface ThresholdEvaluation {
  multiplier: number
  precision: number | null
  recall: number | null
  f1: number | null
  tp: number
  fp: number
  tn: number
  fn: number
}

export interface Suggestion {
  run_id: number | null
  /** 实际参与比较的算法（后端特意避开 candidates 这个键名）。 */
  evaluated_detectors: string[]
  current_detector: string
  suggested_detector: string
  detector_changed: boolean
  current_multiplier: number
  suggested_multiplier: number
  reason: string
  current: ThresholdEvaluation | null
  best: ThresholdEvaluation | null
  candidates: SuggestionCandidate[]
}

/** 候选设置的一行评估。字段与 ThresholdEvaluation 同构。 */
export type SuggestionCandidate = ThresholdEvaluation & {
  detector?: string
}

// ─────────────────────────────────────────── 评估报告 /api/summary

export interface EvalBucket {
  n_series: number
  n_truth: number
  n_pred: number
  precision: number
  recall: number
  f1: number
  range_f1: number
  elapsed_ms: number
}

export interface EvaluationRow {
  series_id: string
  metric_class: string
  detector: string
  score_type: string
  threshold: number
  precision: number
  recall: number
  f1: number
  range_f1: number
  n_truth: number
  n_pred: number
  elapsed_ms: number
  /** 序列的时间范围（秒精度）—— 用于按时间筛选。 */
  start_ts?: string
  end_ts?: string
  /** 数据来源维度 —— 用于按来源聚合。 */
  source?: string
}

/** 被排除的检测记录（评估报告里可恢复）。 */
export interface Exclusion {
  key: string
  series_id: string
  detector: string
  excluded_at: string
}

export interface Summary {
  generated_at: string | null
  title: string
  summary: {
    overall?: EvalBucket
    by_detector?: Record<string, EvalBucket>
    by_metric_class?: Record<string, EvalBucket>
  }
  rows: EvaluationRow[]
  /** 被排除的检测记录（可在「已排除记录」里恢复）。 */
  excluded?: Exclusion[]
}

// ─────────────────────────────────────────── Bad Case /api/badcases

export interface Badcase {
  kind: string
  group: string
  reason: string
  indices: number[]
}

export interface Badcases {
  series_id: string
  detector: string
  threshold: number
  score_type: string
  timestamps: string[]
  values: number[]
  scores: number[]
  /**
   * 基线三件套：实际值 vs 「正常值应该在哪儿」。
   *
   * - `baseline`：基线（统计型 = 中心值；预测型 = 重构值/预测中位数）
   * - `lower`/`upper`：容忍带 / 预测区间
   *
   * 不支持的检测器返回 null；有值时长度与 values 一致。
   * 单点缺失（预测型的未覆盖段）用 null 表示，前端会断线而不是画假基线。
   */
  baseline: (number | null)[] | null
  lower: (number | null)[] | null
  upper: (number | null)[] | null
  /**
   * 带的语义：
   * - `alert_boundary`：带边界 = 告警阈值（值出带即判异常）
   * - `prediction_interval`：模型自己的预测区间（不是告警边界）
   */
  band_kind: 'alert_boundary' | 'prediction_interval' | null
  badcases: Badcase[]
}

// ─────────────────────────────────────────── 标注 /api/annotate/{series_id}

export interface Annotation {
  series_id: string
  /** 区间起点（naive ISO 字符串）—— 不是数组下标。 */
  start: string
  /** 区间终点（naive ISO 字符串）—— 不是数组下标。 */
  end: string
  type: string
  created_at: string
}

export interface AnnotationList {
  series_id: string
  run_id: number | null
  intervals: Annotation[]
}

// ───────────────────────────────────── 生产评估 /api/evaluation/production

/** 一条可标注的生产检测记录。 */
export interface ProductionSample {
  run_id: number
  series_id: string
  group: string | null
  job_id: number
  detector: string
  source_id: number
  source_name: string
  metric_id: number
  metric_name: string
  n: number
  n_alerts: number
  start_ts: string
  end_ts: string
  n_annotations: number
  n_truth: number
  /** 这次运行的时间段**用户核对过**吗 —— 没核对过就没法评估。 */
  reviewed: boolean
  /** 检出结果 —— 「报出了告警」还是「什么都没报」。 */
  outcome: 'alert' | 'normal'
  outcome_label: string
  /** 它被抽中时所在层的采样率 —— 标注时要一起存下来。 */
  rate: number
  /** 它所在层的候选总量。 */
  layer_size: number
}

/** 生产评估的一行 —— 一条检测记录 × 它的标注。 */
export interface ProductionEvaluationRow {
  run_id: number
  series_id: string
  group: string | null
  job_id: number
  detector: string
  source_id: number
  source_name: string
  metric_id: number
  metric_name: string
  start_ts: string
  end_ts: string
  n: number
  n_truth: number
  n_pred: number
  n_annotations: number
  /** 检出结果 —— 「报出了告警」还是「什么都没报」。 */
  outcome: 'alert' | 'normal'
  outcome_label: string
  /** 这条记录被抽中时所在层的采样率。 */
  rate: number
  /** 权重 = 1 / rate —— 这条代表总体里的多少条。 */
  weight: number
  /** 加权前的计数。 */
  tp: number
  fp: number
  fn: number
  precision: number
  recall: number
  f1: number
  range_f1: number
}

/** 采样信息 —— 抽了多少、标了多少。 */
export interface ProductionSampling {
  /** 异常层（报出了告警）的采样比例。 */
  rate_alert: number
  /** 正常层（什么都没报）的采样比例 —— 正常记录远多于异常记录。 */
  rate_normal: number
  /** 候选总数（全部运行记录 × 全部序列）。 */
  n_candidates: number
  /** 采样选中的条数。 */
  n_sampled: number
  /** 采样选中且已标注的条数。 */
  n_annotated: number
  /** 每层抽样的条数上限（null = 不限）。 */
  max_per_layer: number | null
  /** 去重后的告警事件数 —— 同一区间被反复报出只算一个。 */
  n_events: number
  layers: ProductionLayer[]
}

/** 一层（数据源 → 指标 → 检出结果）的采样与成绩。 */
export interface ProductionLayer {
  source_id: number
  source_name: string
  metric_id: number
  metric_name: string
  /** 检出结果 —— 「异常」（报出了告警）或「正常」（什么都没报）。 */
  outcome: 'alert' | 'normal'
  outcome_label: string
  /** 层内检测记录数 —— 总体的口径。 */
  n_candidates: number
  /** 层内不同检测内容数 —— 诊断用：活数据源每次检测都不同（两者相等）。 */
  n_contents: number
  /** 去重后的告警事件数 —— 同一区间被反复报出只算一个。 */
  n_events: number
  n_sampled: number
  n_annotated: number
  /** 这一层实际生效的采样率。 */
  rate: number
  precision: number | null
  recall: number | null
  f1: number | null
  range_f1: number | null
}

/** 生产评估的完整结果 —— 按「数据源 → 指标」分层。 */
export interface ProductionEvaluation {
  rows: ProductionEvaluationRow[]
  layers: ProductionLayer[]
  sampling: ProductionSampling
  overall: {
    n_samples: number
    n_layers: number
    precision: number | null
    recall: number | null
    f1: number | null
    range_f1: number | null
    n_truth: number
    n_alerts: number
    /** 反算出来的总体量（加权后的计数之和）。 */
    n_estimated: number
    /** 加权后的命中 / 误报 / 漏报。 */
    tp: number
    fp: number
    fn: number
  }
  n_candidates: number
  warnings: string[]
}

/** 某次运行里一条序列的完整时序。 */
export interface RunSeriesDetail {
  run_id: number
  series_id: string
  detector: string
  /** 尺度来源（iqr / mad / std / none）；老产物为空串。 */
  scale_source: string
  /** 尺度是否可用；老产物按 ok 返回。 */
  status: 'ok' | 'undetermined'
  /** 尺度是否降级过；老产物按 false 返回。 */
  scale_fallback: boolean
  timestamps: string[]
  values: number[]
  scores: number[]
  severity: number[]
  /** 生产数据没有自带真值 —— 恒为空，真值来自人工标注。 */
  labels: number[]
}

// ─────────────────────────────────────────── 序列 /api/series

export interface SeriesMeta {
  series_id: string
  metric_class: string
  n: number
  n_anomalies: number
  /** 序列时间范围（ISO 字符串）—— 前端按它筛时间。 */
  start_ts: string | null
  end_ts: string | null
  /** 数据来源维度 —— 评估报告按它聚合。 */
  source: string
}

export interface SeriesValues {
  series_id: string
  timestamps: string[]
  values: number[]
  labels: number[]
}

// ─────────────────────────────────────────── 指标预检 /api/lab/inspect

/** 采样参数 —— 必须与未来检测任务的窗口一致，否则结论不可迁移。 */
export interface LabSampling {
  mode: 'recent' | 'even' | 'stratified'
  window_points: number
  stride_points: number | null
  max_points: number
  max_windows: number
  min_valid_ratio: number
  seed: number
}

/** 一个窗口的形态推断结果。 */
export interface LabClassification {
  metric_class: string
  confidence: number
  reasons: string[]
  candidates: string[]
  params: Record<string, Record<string, unknown>>
  rationale: string
}

/** 一个采样窗口的体检结果。 */
export interface LabWindow {
  index: number
  start: string
  end: string
  n: number
  expected: number
  n_missing: number
  missing_ratio: number
  zero_ratio: number
  duplicate_timestamps: number
  on_grid_ratio: number
  median_interval_s: number | null
  min: number | null
  max: number | null
  mean: number | null
  std: number | null
  sufficient: boolean
  insufficient_reason: string | null
  classification: LabClassification | null
  classification_reason: string | null
}

/** 序列级形态聚合（多数类 + 一致性）。 */
export interface LabShape {
  metric_class: string
  confidence: number
  consistency: number
  candidates: string[]
  n_classified: number
  n_windows: number
}

/** 一条序列的预检结果。 */
export interface LabSeries {
  series_id: string
  group: string | null
  n: number
  /** 序列**实际**覆盖的时间起点（UTC ISO）—— 选范围时要看它，别只看请求范围。 */
  data_start: string | null
  /** 序列实际覆盖的时间终点（UTC ISO）。 */
  data_end: string | null
  windows: LabWindow[]
  shape: LabShape | null
}

/** 当前窗口长度能识别到的周期。 */
export interface LabPeriodCapability {
  daily_points: number
  daily_ok: boolean
  weekly_points: number
  weekly_ok: boolean
  max_period_points: number
}

/** 一次预检的完整结果。 */
export interface LabInspectResult {
  spec: Record<string, unknown>
  freq: string
  window_points: number
  sampling: LabSampling
  period_capability: LabPeriodCapability
  series: LabSeries[]
  warnings: string[]
}

// ─────────────────────────────────── 多算法实验 /api/lab/run

/** 一个窗口 × 一个检测器的检测结果。 */
export interface LabWindowDetection {
  series_id: string
  window_index: number
  /** 实际使用的算法名 —— `auto` 是逐窗口解析的。 */
  detector: string
  requested: string
  metric_class: string | null
  /** 没有按推荐走（推断不可靠或平台不支持）。 */
  fallback: boolean
  rationale: string
  n: number
  n_alerts: number
  alert_ratio: number
  elapsed_ms: number
  /** 倍数 → 该倍数下的检出点数。 */
  sensitivity: Record<string, number>
  /** 数据不足被跳过。 */
  skipped: boolean
  skip_reason: string | null
}

/** 一个检测器在所有窗口上的汇总画像。 */
export interface LabDetectorAggregate {
  n_windows: number
  n_windows_skipped: number
  n_points: number
  n_alerts: number
  alert_ratio: number
  n_windows_with_alerts: number
  /** 各窗口检出率的离散度 —— 越小越稳。 */
  stability: number | null
  elapsed_ms: number
  /** 倍数 → 总检出点数。 */
  sensitivity: Record<string, number>
  /** 实际使用的算法 → 窗口数（`auto` 会用到多个）。 */
  resolved_mix: Record<string, number>
}

export interface LabDetectorRun {
  detector: string
  per_window: LabWindowDetection[]
  aggregate: LabDetectorAggregate
}

/** 一次多算法对比实验的结果。 */
export interface LabRunResult {
  spec: LabSpec
  freq: string
  window_points: number
  multipliers: string[]
  primary_multiplier: string
  windows: Array<{
    series_id: string
    index: number
    start: string
    end: string
    n: number
    expected: number
    sufficient: boolean
    missing_ratio: number
  }>
  results: LabDetectorRun[]
  warnings: string[]
}

/** 一次实验的完整描述 —— 前端拿它就能原样再发一次请求。 */
export interface LabSpec {
  kind: string
  metric_id: number | null
  source_id: number | null
  sql: string | null
  time_column: string | null
  value_column: string | null
  group_column: string | null
  time_format: string
  source_timezone: string
  freq: string | null
  missing_policy: string | null
  max_series: number
  start: string
  end: string
  sampling: {
    mode: string
    window_points: number
    stride_points: number | null
    max_points: number
    max_windows: number
    min_valid_ratio: number
    seed: number
  }
  /** 真值来源：`none` = 无真值；`annotation` = 人工标注。 */
  truth: string
  synthetic: {
    metric_class: string
    n_points: number
    n_anomalies: number
    anomaly_types: string[]
    seed: number
  }
  public: {
    dataset: string
    name: string | null
    limit: number
  }
}

// ─────────────────────────────────── 有真值评估 /api/lab/evaluate

/** 一组 P / R / F1。 */
export interface LabEvalMetrics {
  threshold: number
  precision: number
  recall: number
  f1: number
  /** 区间级 F1 —— 按窗口取平均。 */
  range_f1: number
  n_alerts: number
  n_truth: number
  n_windows: number
}

/** 一次有真值评估的结果。 */
export interface LabEvaluateResult {
  spec: LabSpec
  truth: {
    sources: string[]
    n_series_with_truth: number
    n_truth_points: number
  }
  split: {
    ratio: number
    calibration_windows: number
    test_windows: number
  }
  results: Array<{
    detector: string
    /** `auto` 逐窗实际用了哪些算法。 */
    resolved_mix: Record<string, number>
    calibration: {
      threshold: number | null
      n_windows_used: number
      n_windows_skipped: number
      per_window: Array<{
        series_id: string
        window_index: number
        threshold: number
        f1: number
      }>
      metrics: LabEvalMetrics | null
    }
    test: LabEvalMetrics | null
    /** 平台默认阈值（2.5）在测试集上的表现 —— 用户的对照基准。 */
    default_threshold: LabEvalMetrics | null
    sensitivity: Array<LabEvalMetrics>
  }>
  warnings: string[]
}

// ─────────────────────────────────── 单窗口时序 /api/lab/window

/** 一个算法在单个窗口上的完整输出。 */
export interface LabWindowDetector {
  /** 请求的算法名（可能是 `auto`）。 */
  detector: string
  /** 实际用的算法（`auto` 会逐窗解析）。 */
  resolved: string
  metric_class: string | null
  fallback: boolean
  rationale: string
  scores: (number | null)[]
  /** 0 = 正常，1 = P1，2 = P0。 */
  severity: number[]
  baseline: (number | null)[]
  lower: (number | null)[]
  upper: (number | null)[]
  n_alerts: number
  multiplier: number
}

/** 单个窗口的时序数据 —— 画图用。 */
export interface LabWindowDetail {
  series_id: string
  window_index: number
  start: string
  end: string
  freq: string
  n: number
  expected: number
  missing_ratio: number
  /** 毫秒时间戳。 */
  timestamps: number[]
  values: (number | null)[]
  detectors: LabWindowDetector[]
  warnings: string[]
}

// ─────────────────────────────────── 实验记录 /api/lab/experiments

/** 实验记录里存的 spec —— 复现时要靠它。 */
export interface LabExperimentSpec {
  kind: string
  metric_id: number | null
  metric_name: string | null
  source_id: number | null
  freq: string | null
  start: string
  end: string
  sampling: {
    mode: string
    window_points: number
    stride_points: number | null
    max_points: number
    max_windows: number
    min_valid_ratio: number
    seed: number
  }
  detectors: string[] | null
  multipliers: number[] | null
  [key: string]: unknown
}

/** 环境快照 —— git sha + Python + 依赖版本。 */
export interface LabExperimentEnv {
  git_sha: string | null
  git_dirty: boolean | null
  python: string
  dependencies: Record<string, string | null>
}

/** 实验记录摘要（列表页用）。 */
export interface LabExperimentSummary {
  id: string
  created_at: string
  fingerprint: string
  spec: LabExperimentSpec
  summary: {
    n_windows: number
    detectors: Array<{
      detector: string
      n_windows: number | null
      n_alerts: number | null
      alert_ratio: number | null
      stability: number | null
    }>
    warnings: string[]
  }
}

/** 实验记录详情（含完整结果）。 */
export interface LabExperiment extends LabExperimentSummary {
  version: number
  env: LabExperimentEnv
  result: LabRunResult
}

/** 从实验记录生成的任务草稿 —— 只回填表单，不创建任务。 */
export interface LabJobDraft {
  metric_id: number
  name: string
  detector: string
  window_points: number
  interval_seconds: number
  alert_threshold: number
  critical_threshold: number
  alert_rules: AlertRule[]
  /** 实验里跑过的其它算法 —— 让用户自己挑，不替他决定。 */
  alternatives: string[]
  rationale: string
  experiment_id: string
}
