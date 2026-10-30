import { describe, expect, it } from 'vitest'
import type { CompareDetector } from '../../api/types'
import { candidateNames, defaultSelection } from './ComparePicker'
import { buildCompareOption } from './CompareChart'
import { maxScoreOf, topSeverityOf } from './CompareTable'

const detector = (over: Partial<CompareDetector> = {}): CompareDetector => ({
  name: 'iqr',
  score_type: 'mad',
  default_threshold: 2.5,
  baseline: [1, 2, 3],
  lower: [0, 1, 2],
  upper: [2, 3, 4],
  scores: [0.1, 0.2, 0.3],
  severity: [0, 0, 0],
  n_alerts: 0,
  n_top: 0,
  is_auto: false,
  ...over,
})

describe('candidateNames', () => {
  it('available 有内容时用它', () => {
    expect(candidateNames(['iqr', 'mad'], ['seasonal'])).toEqual(['iqr', 'mad'])
  })

  it('available 为空时回退到 detectors 的名字列表', () => {
    expect(candidateNames([], ['seasonal', 'stl_residual'])).toEqual([
      'seasonal',
      'stl_residual',
    ])
  })
})

describe('defaultSelection', () => {
  it('候选 ≤4 个时全勾', () => {
    expect(defaultSelection(['a', 'b', 'c', 'd'], 'a')).toEqual(['a', 'b', 'c', 'd'])
    expect(defaultSelection(['a', 'b'], 'b')).toEqual(['a', 'b'])
  })

  it('候选 >4 个时只勾 auto', () => {
    expect(defaultSelection(['a', 'b', 'c', 'd', 'e'], 'c')).toEqual(['c'])
  })

  it('auto 不在候选里时勾选为空（交给后端比全部）', () => {
    expect(defaultSelection(['a', 'b', 'c', 'd', 'e'], 'zzz')).toEqual([])
  })
})

describe('topSeverityOf', () => {
  it('取 severity 的最大值', () => {
    expect(topSeverityOf([0, 1, 2, 1])).toBe(2)
  })

  it('空数组返回 0（对应「正常」档）', () => {
    expect(topSeverityOf([])).toBe(0)
  })

  it('全是 0 时返回 0', () => {
    expect(topSeverityOf([0, 0, 0])).toBe(0)
  })
})

describe('maxScoreOf', () => {
  it('取最大值', () => {
    expect(maxScoreOf([0.1, 3.5, 2])).toBe(3.5)
  })

  it('⚠️ 过滤 null —— 否则 Math.max 会得到 NaN', () => {
    expect(maxScoreOf([null, 2.5, null])).toBe(2.5)
  })

  it('全是 null 时返回 null（显示「—」）', () => {
    expect(maxScoreOf([null, null])).toBeNull()
  })

  it('空数组返回 null', () => {
    expect(maxScoreOf([])).toBeNull()
  })
})

describe('buildCompareOption', () => {
  const base = {
    timestamps: ['t0', 't1', 't2'],
    values: [1, 2, 3] as (number | null)[],
  }

  it('实际值是一条线', () => {
    const option = buildCompareOption({ ...base, detectors: [] })
    expect(option.series[0].name).toBe('实际值')
    expect(option.series[0].type).toBe('line')
  })

  it('每个算法一条基线 + 一组告警散点', () => {
    const option = buildCompareOption({
      ...base,
      detectors: [
        detector({ name: 'iqr', severity: [0, 1, 0] }),
        detector({ name: 'mad', baseline: null, severity: [0, 2, 0] }),
      ],
    })
    const names = option.series.map((s) => s.name)
    expect(names).toContain('iqr 基线')
    expect(names).toContain('iqr 告警')
    expect(names).toContain('mad 告警')
    expect(names).not.toContain('mad 基线') // 没有基线就不画基线
  })

  it('没有告警点的算法不产生散点系列', () => {
    const option = buildCompareOption({
      ...base,
      detectors: [detector({ name: 'iqr', severity: [0, 0, 0] })],
    })
    expect(option.series.map((s) => s.name)).not.toContain('iqr 告警')
  })

  it('告警散点只收 severity>0 且有值的点', () => {
    const option = buildCompareOption({
      ...base,
      values: [1, null, 3],
      detectors: [detector({ name: 'iqr', severity: [1, 1, 1] })],
    })
    const scatter = option.series.find((s) => s.name === 'iqr 告警')
    expect((scatter?.data as unknown[]).length).toBe(2)
  })

  it('图例包含实际值与各算法的基线/告警', () => {
    const option = buildCompareOption({
      ...base,
      detectors: [detector({ name: 'iqr', severity: [0, 1, 0] })],
    })
    expect(option.legend?.data).toEqual(['实际值', 'iqr 基线', 'iqr 告警'])
  })

  it('实际值线不断线（connectNulls 不开）', () => {
    const option = buildCompareOption({ ...base, detectors: [] })
    expect(option.series[0].connectNulls).not.toBe(true)
  })

  it('dataZoom 有 inside 与 slider', () => {
    const option = buildCompareOption({ ...base, detectors: [] })
    expect(option.dataZoom?.length).toBe(2)
  })
})
