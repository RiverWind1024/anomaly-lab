import { describe, expect, it } from 'vitest'
import type { EvaluationRow } from '../../api/types'
import {
  indexOfRow,
  isSelectedRow,
  paginate,
  recordKey,
  resolveSelected,
  totalPages,
} from './records'

function row(seriesId: string, detector: string, extra: Partial<EvaluationRow> = {}) {
  return {
    series_id: seriesId,
    detector,
    metric_class: 'periodic',
    score_type: 'zscore',
    threshold: 2.5,
    precision: 1,
    recall: 0.5,
    f1: 0.667,
    range_f1: 0.5,
    n_truth: 2,
    n_pred: 1,
    elapsed_ms: 0.1,
    ...extra,
  } as EvaluationRow
}

const rows = [
  row('a', 'iqr'),
  row('a', 'mad'),
  row('b', 'iqr'),
  row('c', 'mad'),
]

describe('resolveSelected', () => {
  it('没有 series_id → 没选中', () => {
    expect(resolveSelected(rows, undefined, undefined)).toBeUndefined()
  })

  it('URL 给了 detector → 直接用', () => {
    expect(resolveSelected(rows, 'a', 'mad')).toEqual({
      series_id: 'a',
      detector: 'mad',
    })
  })

  it('⚠️ 只有 series_id → 按报告里的第一条解析算法', () => {  // taste-skill-ignore
    // 旧深链接（评估页改造前发出的）只有序列号
    expect(resolveSelected(rows, 'b', undefined)).toEqual({
      series_id: 'b',
      detector: 'iqr',
    })
  })

  it('报告里没有这条序列 → 算法留空（让端点按默认去试）', () => {
    expect(resolveSelected(rows, 'zzz', undefined)).toEqual({
      series_id: 'zzz',
      detector: undefined,
    })
  })
})

describe('isSelectedRow', () => {
  it('序列 + 算法都对上 → 选中', () => {
    expect(isSelectedRow(rows[1], { series_id: 'a', detector: 'mad' })).toBe(true)
  })

  it('⚠️ 同序列不同算法 → 不选中', () => {  // taste-skill-ignore
    // 只按序列比会把同序列的所有算法一起点亮 —— 那是个 bug
    expect(isSelectedRow(rows[0], { series_id: 'a', detector: 'mad' })).toBe(false)
  })

  it('没选中 → 全都不选中', () => {
    expect(isSelectedRow(rows[0], undefined)).toBe(false)
  })
})

describe('indexOfRow', () => {
  it('找到 → 序号', () => {
    expect(indexOfRow(rows, { series_id: 'c', detector: 'mad' })).toBe(3)
  })

  it('找不到 → -1', () => {
    expect(indexOfRow(rows, { series_id: 'zzz', detector: 'mad' })).toBe(-1)
    expect(indexOfRow(rows, undefined)).toBe(-1)
  })
})

describe('paginate', () => {
  const items = Array.from({ length: 25 }, (_, i) => i)

  it('第一页', () => {
    expect(paginate(items, 1, 10)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
  })

  it('第三页（不足一页）', () => {
    expect(paginate(items, 3, 10)).toEqual([20, 21, 22, 23, 24])
  })

  it('页码越界 → 空', () => {
    expect(paginate(items, 9, 10)).toEqual([])
  })

  it('pageSize 非法 → 空', () => {
    expect(paginate(items, 1, 0)).toEqual([])
  })
})

describe('totalPages', () => {
  it('刚好整除', () => {
    expect(totalPages(120, 20)).toBe(6)
  })

  it('有余数 → 向上取整', () => {
    expect(totalPages(121, 20)).toBe(7)
  })

  it('空列表也是 1 页（不是 0 页）', () => {
    expect(totalPages(0, 20)).toBe(1)
  })
})

describe('recordKey', () => {
  it('序列 + 算法 才唯一', () => {
    expect(recordKey(rows[0])).not.toBe(recordKey(rows[1]))
  })
})
