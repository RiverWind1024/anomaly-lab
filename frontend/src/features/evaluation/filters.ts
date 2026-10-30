import type { EvaluationRow } from '../../api/types'

/** 可聚合的维度。 */
export type DimensionKey = 'metric_class' | 'detector' | 'source'

export const DIMENSIONS: Array<{ key: DimensionKey; label: string }> = [
  { key: 'metric_class', label: '形态' },
  { key: 'detector', label: '检测算法' },
  { key: 'source', label: '数据来源' },
]

export interface EvaluationFilters {
  /** 起始时间（含）—— 格式 'YYYY-MM-DDTHH:mm:ss' */
  since?: string
  /** 结束时间（含） */
  until?: string
  detector?: string
  metricClass?: string
  source?: string
}

/**
 * 按条件过滤评估记录。
 *
 * ⚠️ 时间筛选用的是**区间相交**，不是完全包含 ——
 *    「这段时间有异常」意味着这段时间的序列**与**该区间有重叠。
 */
export function filterRows(rows: EvaluationRow[], filters: EvaluationFilters): EvaluationRow[] {
  return rows.filter((row) => {
    if (filters.detector && row.detector !== filters.detector) return false
    if (filters.metricClass && row.metric_class !== filters.metricClass) return false
    if (filters.source && (row.source ?? '') !== filters.source) return false
    if (filters.since && row.end_ts && row.end_ts < filters.since) return false
    if (filters.until && row.start_ts && row.start_ts > filters.until) return false
    return true
  })
}

/** 某一列的候选值（从数据里汇总，去重排序）。 */
export function distinctValues(rows: EvaluationRow[], pick: (row: EvaluationRow) => string): string[] {
  const values = new Set<string>()
  for (const row of rows) {
    const value = pick(row)
    if (value) values.add(value)
  }
  return [...values].sort()
}
