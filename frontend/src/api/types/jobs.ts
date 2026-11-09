/** API 类型：告警规则 / 运行记录 / 检测记录 / 预览 / 对比 / 试跑。 */
import type { AlertDirection } from './common'
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

// ───────────────────────────── 平台检测记录 /api/platform/detections

/**
 * 一次运行 × 一条序列的检测记录。
 *
 * ⚠️ 与离线评估的 `EvaluationRow` 不是一回事：
 *    那边是「算法在合成集上表现如何」，这里是「任务实际跑出了什么」。
 */
export interface DetectionRecord {
  run_id: number
  job_id: number
  job_name: string
  metric_id: number
  metric_name: string
  source_name: string
  started_at: string
  series_id: string
  group: string | null
  n: number
  n_valid: number
  n_missing: number
  n_alerts: number
  n_p0: number
  sufficient: boolean
  detector: string
  metric_class: string
  fallback: boolean
  start_ts: string
  end_ts: string
  /** 尺度来源（iqr / mad / std / poisson / none）；老数据为空串。 */
  scale_source: string
  scale_fallback: boolean
  status: 'ok' | 'undetermined'
  /** 这次运行有没有留下决策链；老数据可能没有。 */
  has_decision: boolean
}

export interface DetectionRecordList {
  records: DetectionRecord[]
  total: number
  limit: number
  offset: number
  jobs: Array<{ id: number; name: string }>
}

// ─────────────────────────────────────────── 预览 /api/platform/jobs/{id}/preview

// ─────────────────────────────────────────── 数据能力探测

/** 某条能力警告针对的算法（iqr / mad / zscore / zero_inflated_iqr）。 */
export interface CapabilityWarningItem {
  detector: string
  reason: string
}

/** 这个指标会让哪些算法失效 —— 只报告，不改数据。 */
export interface Capability {
  zero_ratio: number
  n_nonzero: number
  /**
   * 数据是否像非负整数计数（泊松 / 事件计数类算法的前提）。
   * 老产物没有这个键。
   */
  count_ready?: boolean
  verdict: 'ok' | 'unsuitable' | 'undetermined'
  warnings: CapabilityWarningItem[]
  message: string
  /**
   * 「算法 × 形态」不适配的说明（无周期、趋势不近似线性）。
   *
   * ⚠️ 与 `warnings` 分开：这类问题不改变 `verdict` ——
   *    数据本身没病，只是这几个算法不适用。老产物没有这个键。
   */
  shape_warnings?: CapabilityWarningItem[]
  /** 有没有可信周期（`seasonal` / `stl_residual` 的前提）。 */
  has_period?: boolean
  /** 线性去趋势后残差的结构强度（0–1）。 */
  detrended_structure?: number
}

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
  /** 检测器的首选尺度（iqr / mad / std）；没有该属性的算法为空串。 */
  scale_prefer?: string
  /** 本次运行的告警方向（老产物没有这个键）。 */
  alert_direction?: AlertDirection
  /**
   * 方向是否真的生效了。
   * `false` = 配了 `below` 但算法没有基线，本次一条没报。
   */
  direction_applied?: boolean
  /** 这个指标会让哪些算法失效；数据不足时没有这个键。 */
  capability?: Capability
  file: string | null
}

/** 一次检测的决策链。各段按需存在，老数据可能没有。 */
export interface DecisionTraceData {
  quality?: Record<string, unknown>
  capability?: Record<string, unknown>
  classify?: Record<string, unknown>
  select?: Record<string, unknown>
  threshold?: Record<string, unknown>
  detect?: Record<string, unknown>
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
  /** 告警方向；老数据没有这个字段。 */
  alert_direction?: 'both' | 'above' | 'below'
  /** 告警方向是否真的生效；`false` 表示算法没有基线，方向无从判断。 */
  direction_applied?: boolean
  /** 决策链；老数据没有这个字段（或为 `{}`），前端整块不渲染。 */
  decision?: DecisionTraceData
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
  /** 本次试跑用的告警方向（旧后端没有这个字段）。 */
  alert_direction?: AlertDirection
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
  /** 这个指标会让哪些算法失效；数据不足时没有这个键。 */
  capability?: Capability
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

