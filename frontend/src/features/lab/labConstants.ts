/** Lab 的类型、选项与表单默认值。 */

export type Kind = 'metric' | 'sql' | 'synthetic'

/** 真值来源 —— 只有已有指标 / 临时 SQL 才需要指明。 */
export type TruthKind = 'none' | 'annotation'

/** 预检与对比实验共用的请求体。 */
export interface LabRequest {
  kind: 'metric' | 'sql' | 'synthetic'
  start: string
  end: string
  metric_id?: number
  source_id?: number
  sql?: string
  time_column?: string
  value_column?: string
  group_column?: string | null
  freq?: string
  time_format?: string
  source_timezone?: string
  truth?: TruthKind
  synthetic?: {
    metric_class: string
    n_points: number
    n_anomalies: number
    anomaly_types: string[]
    seed: number
  }
  sampling: SamplingForm
}

/** 合成数据的参数 —— 「算法能力参照系」，自带真值。 */
export interface SyntheticForm {
  metric_class: string
  n_points: number
  n_anomalies: number
  seed: number
  freq: string
}

export const METRIC_CLASS_OPTIONS = [
  { value: 'stationary', label: '平稳' },
  { value: 'periodic', label: '周期' },
  { value: 'trending', label: '趋势' },
  { value: 'step', label: '阶跃' },
  { value: 'high_zero_ratio', label: '高零占比' },
  { value: 'sparse_event', label: '稀疏事件' },
]

/** 频率 → 秒 —— 合成数据的时长要按它算。 */
export const FREQ_SECONDS: Record<string, number> = { s: 1, min: 60, m: 60, h: 3600, d: 86400 }

export function freqSeconds(freq: string): number {
  const match = /^(\d+)(s|min|m|h|d)$/.exec(freq.trim().toLowerCase())
  if (!match) return 300
  return Number(match[1]) * (FREQ_SECONDS[match[2]] ?? 60)
}

/** 可选的检测器 —— 留空让后端按形态推荐。 */
export const DETECTOR_OPTIONS = [
  { value: 'auto', label: '自动推荐' },
  { value: 'iqr', label: 'IQR 围栏' },
  { value: 'mad', label: 'MAD' },
  { value: 'zscore', label: 'Z 分数' },
  { value: 'seasonal', label: '季节性分组' },
  { value: 'stl_residual', label: 'STL 残差' },
  { value: 'trend_residual_iqr', label: '去趋势残差 IQR' },
  { value: 'theil_sen', label: '稳健趋势线 Theil-Sen' },
]

export interface SamplingForm {
  mode: 'recent' | 'even' | 'stratified'
  window_points: number
  max_points: number
  max_windows: number
  min_valid_ratio: number
}

export interface SqlForm {
  sql: string
  time_column: string
  value_column: string
  group_column: string
  freq: string
  time_format: string
  source_timezone: string
}

export const DEFAULT_SAMPLING: SamplingForm = {
  mode: 'even',
  window_points: 500,
  max_points: 10_000,
  max_windows: 100,
  min_valid_ratio: 0.8,
}

export const DEFAULT_SQL: SqlForm = {
  sql: '',
  time_column: 'ts',
  value_column: 'value',
  group_column: '',
  freq: '5min',
  time_format: 'iso_utc',
  source_timezone: 'UTC',
}

export const DEFAULT_SYNTHETIC: SyntheticForm = {
  metric_class: 'periodic',
  n_points: 2000,
  n_anomalies: 5,
  seed: 42,
  freq: '5min',
}

