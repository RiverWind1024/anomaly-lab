import { describe, expect, it } from 'vitest'
import { aggregateBy } from './aggregate'
import { distinctValues, filterRows } from './filters'
import type { EvaluationRow } from '../../api/types'

const ROWS: EvaluationRow[] = [
  {
    series_id: 's-1',
    metric_class: 'periodic',
    detector: 'iqr',
    score_type: 'zscore',
    threshold: 2.5,
    precision: 1.0,
    recall: 0.5,
    f1: 0.667,
    range_f1: 0.5,
    n_truth: 2,
    n_pred: 1,
    elapsed_ms: 0.1,
    start_ts: '2026-01-01T00:00:00',
    end_ts: '2026-01-02T00:00:00',
    source: 'synthetic',
  },
  {
    series_id: 's-2',
    metric_class: 'periodic',
    detector: 'mad',
    score_type: 'zscore',
    threshold: 3.0,
    precision: 0.5,
    recall: 0.5,
    f1: 0.5,
    range_f1: 0.4,
    n_truth: 4,
    n_pred: 2,
    elapsed_ms: 0.2,
    start_ts: '2026-01-05T00:00:00',
    end_ts: '2026-01-06T00:00:00',
    source: 'synthetic',
  },
  {
    series_id: 's-3',
    metric_class: 'trending',
    detector: 'iqr',
    score_type: 'zscore',
    threshold: 2.5,
    precision: 0.25,
    recall: 0.25,
    f1: 0.25,
    range_f1: 0.2,
    n_truth: 8,
    n_pred: 3,
    elapsed_ms: 0.3,
    start_ts: '2026-01-10T00:00:00',
    end_ts: '2026-01-11T00:00:00',
    source: 'synthetic',
  },
]

describe('filterRows', () => {
  it('按检测算法筛', () => {
    const out = filterRows(ROWS, { detector: 'iqr' })
    expect(out.map((r) => r.series_id)).toEqual(['s-1', 's-3'])
  })

  it('按形态筛', () => {
    const out = filterRows(ROWS, { metricClass: 'periodic' })
    expect(out).toHaveLength(2)
  })

  it('时间筛选取**相交**的记录，不是完全包含', () => {
    // 与 s-1 的区间（01-01 ~ 01-02）相交
    const out = filterRows(ROWS, {
      since: '2026-01-02T00:00:00',
      until: '2026-01-05T00:00:00',
    })
    expect(out.map((r) => r.series_id)).toEqual(['s-1', 's-2'])
  })

  it('完全不重叠的时间范围筛不到任何记录', () => {
    const out = filterRows(ROWS, {
      since: '2026-02-01T00:00:00',
      until: '2026-02-02T00:00:00',
    })
    expect(out).toEqual([])
  })
})

describe('distinctValues', () => {
  it('汇总候选值并去重排序', () => {
    expect(distinctValues(ROWS, (row) => row.detector)).toEqual(['iqr', 'mad'])
    expect(distinctValues(ROWS, (row) => row.metric_class)).toEqual(['periodic', 'trending'])
  })
})

describe('aggregateBy', () => {
  it('按形态聚合', () => {
    const out = aggregateBy(ROWS, 'metric_class')
    const periodic = out.find((b) => b.key === 'periodic')
    expect(periodic?.n_series).toBe(2)
    expect(periodic?.precision).toBeCloseTo(0.75)
    expect(periodic?.n_truth).toBe(6)
  })

  it('按检测算法聚合', () => {
    const out = aggregateBy(ROWS, 'detector')
    expect(out.find((b) => b.key === 'iqr')?.n_series).toBe(2)
    expect(out.find((b) => b.key === 'mad')?.n_series).toBe(1)
  })

  it('按数据来源聚合', () => {
    const out = aggregateBy(ROWS, 'source')
    expect(out).toHaveLength(1)
    expect(out[0].n_series).toBe(3)
  })

  it('按 F1 降序排', () => {
    const out = aggregateBy(ROWS, 'metric_class')
    expect(out[0].f1).toBeGreaterThanOrEqual(out[1].f1)
  })
})
