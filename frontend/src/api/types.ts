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

export interface CatalogSource {
  id: number
  name: string
  kind: string
  path: string
  created_at: string
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
  /** 查出来的**总**行数（不受 limit 限制）。 */
  total: number
  /** 行数被 limit 截断了。 */
  truncated: boolean
  elapsed_ms: number
}

// ─────────────────────────────────────────── 告警中心 /api/platform/alerts

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
  badcases: Badcase[]
}

// ─────────────────────────────────────────── 标注 /api/annotate/{series_id}

export interface Annotation {
  series_id: string
  start: number
  end: number
  type: string
  created_at: string
}

export interface AnnotationList {
  series_id: string
  intervals: Annotation[]
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
