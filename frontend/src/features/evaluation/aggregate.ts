import type { EvaluationRow } from '../../api/types'
import type { DimensionKey } from './filters'

export interface AggregateBucket {
  key: string
  n_series: number
  n_truth: number
  n_pred: number
  precision: number
  recall: number
  f1: number
  range_f1: number
}

function mean(values: number[]): number {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : NaN
}

/**
 * 按某个维度聚合评估记录。
 *
 * P/R/F1 取**组内均值**（与 report.json 里的 summary 口径一致），
 * 真值点与预测点取**总和**。
 */
export function aggregateBy(rows: EvaluationRow[], dim: DimensionKey): AggregateBucket[] {
  const buckets = new Map<string, EvaluationRow[]>()
  for (const row of rows) {
    const key = String(row[dim] ?? '') || '—'
    const list = buckets.get(key) ?? []
    list.push(row)
    buckets.set(key, list)
  }
  return [...buckets.entries()]
    .map(([key, list]) => ({
      key,
      n_series: list.length,
      n_truth: list.reduce((sum, row) => sum + row.n_truth, 0),
      n_pred: list.reduce((sum, row) => sum + row.n_pred, 0),
      precision: mean(list.map((row) => row.precision)),
      recall: mean(list.map((row) => row.recall)),
      f1: mean(list.map((row) => row.f1)),
      range_f1: mean(list.map((row) => row.range_f1)),
    }))
    .sort((a, b) => b.f1 - a.f1)
}
