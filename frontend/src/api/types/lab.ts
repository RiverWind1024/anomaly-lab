/** API 类型：指标预检（Lab）。 */
import type { AlertRule } from './jobs'
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
  window_seconds: number
  interval_seconds: number
  alert_threshold: number
  critical_threshold: number
  alert_rules: AlertRule[]
  /** 实验里跑过的其它算法 —— 让用户自己挑，不替他决定。 */
  alternatives: string[]
  rationale: string
  experiment_id: string
}

