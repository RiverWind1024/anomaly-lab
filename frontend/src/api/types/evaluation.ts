/** API 类型：离线评估 / Bad Case / 标注 / 生产评估 / 序列。 */
import type { DecisionTraceData } from './jobs'
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
  /** 形态分类（stationary / periodic / ...）；老记录可能为空。 */
  metric_class: string
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
  /** 决策链（数据质量 → 能力 → 形态 → 选算法 → 阈值 → 结果）；老产物为 `{}`。 */
  decision?: DecisionTraceData
  /** 基线三件套；无带的算法是空数组。 */
  baseline?: number[]
  lower?: number[]
  upper?: number[]
  alert_threshold?: number
  critical_threshold?: number
  score_type?: string
  /** 档位名（0 号固定「正常」）。 */
  levels?: string[]
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

