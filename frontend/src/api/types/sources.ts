/** API 类型：数据源 / 指标 / 任务目录 / 数据浏览。 */
import type { AlertDirection } from './common'
import type { AlertRule } from './jobs'

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
  window_seconds: number
  interval_seconds: number
  enabled: boolean
  last_run_at: string | null
  next_run_at: string | null
  created_at: string
  alert_rules: AlertRule[]
  /** 报哪一侧的异常。旧后端没有这个字段时按 `both` 处理。 */
  alert_direction: AlertDirection
  /** 只对窗口最后 N 个点判定告警；0 = 检测整个窗口。旧后端没有这个字段。 */
  detect_points?: number
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
  /**
   * 这个算法支持报哪一侧。
   *
   * `above` = 没有基线，只能报偏高（如 Chronos）。
   * ⚠️ 可选 —— 旧后端没有这个字段，按 `both` 处理。
   */
  direction?: 'both' | 'above'
  /** 首选尺度（iqr / mad / std）；没有尺度概念的算法为 null 或缺失。 */
  prefer_scale?: string | null
  /** 适用性说明；老后端可能没有。 */
  guide?: {
    good_for?: string
    bad_for?: string
    score?: string
    needs?: string
  }
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

