import { describe, expect, it } from 'vitest'
import type { Badcases } from '../../api/types'
import { badcaseLabel, buildDetectionOption, toRanges } from './detectionChart'
import { bandSegments } from '../../lib/bands'

const badcases: Badcases = {
  series_id: 'demo-1',
  detector: 'iqr',
  threshold: 2.5,
  score_type: 'zscore',
  timestamps: ['t0', 't1', 't2', 't3', 't4'],
  values: [1, 2, 3, 4, 5],
  scores: [0.1, 0.2, 3.1, 0.4, 0.5],
  baseline: null,
  lower: null,
  upper: null,
  band_kind: null,
  badcases: [
    {
      kind: 'false_positive',
      group: 'periodic/中段/孤立点',
      reason: '误报：形态=periodic，位置=中段，孤立点',
      indices: [2],
    },
    {
      kind: 'false_negative',
      group: 'periodic/前10%/连续段',
      reason: '漏报：形态=periodic，位置=前10%，连续段',
      indices: [0, 1],
    },
  ],
}

/** 带基线的检测结果（统计型：带边界 = 告警阈值）。 */
const withBand: Badcases = {
  ...badcases,
  baseline: [1, 2, 3, 4, 5],
  lower: [0, 1, 2, 3, 4],
  upper: [2, 3, 4, 5, 6],
  band_kind: 'alert_boundary',
}

describe('toRanges', () => {
  it('连续索引压成一个区间', () => {
    expect(toRanges([0, 1, 2])).toEqual([[0, 2]])
  })

  it('不连续的索引拆成多个区间', () => {
    expect(toRanges([0, 1, 4, 5, 9])).toEqual([
      [0, 1],
      [4, 5],
      [9, 9],
    ])
  })

  it('乱序输入也能正确分段', () => {
    expect(toRanges([3, 1, 2])).toEqual([[1, 3]])
  })

  it('空数组返回空', () => {
    expect(toRanges([])).toEqual([])
  })
})

describe('bandSegments', () => {
  it('连续的 lower/upper 合成一段', () => {
    const segments = bandSegments([0, 1, 2], [2, 3, 4])
    expect(segments).toHaveLength(1)
    expect(segments[0].startIndex).toBe(0)
    expect(segments[0].points).toHaveLength(3)
  })

  it('缺点处断开（不画横跨缺口的假带）', () => {
    const segments = bandSegments([0, null, 2], [2, 3, 4])
    expect(segments).toHaveLength(2)
    expect(segments[0].points).toHaveLength(1)
    expect(segments[1].startIndex).toBe(2)
  })

  it('上下界颠倒的点被跳过', () => {
    const segments = bandSegments([5], [1])
    expect(segments).toHaveLength(0)
  })

  it('长度不一致返回空', () => {
    expect(bandSegments([0], [1, 2])).toHaveLength(0)
  })
})

describe('buildDetectionOption', () => {
  it('⚠️ 用 badcases[].indices 真正画出异常区间（旧版是空对象 markArea，等于没画）', () => {  // taste-skill-ignore
    const option = buildDetectionOption({ data: badcases })
    const value = option.series.find((s) => s.name === '数值')
    const areas = value?.markArea?.data as Array<Array<{ xAxis: number }>>
    expect(areas).toHaveLength(2)
    // 误报区间 [2,2]
    expect(areas[0][0].xAxis).toBe(2)
    expect(areas[0][1].xAxis).toBe(2)
    // 漏报区间 [0,1]
    expect(areas[1][0].xAxis).toBe(0)
    expect(areas[1][1].xAxis).toBe(1)
  })

  it('每个区间都带颜色', () => {
    const option = buildDetectionOption({ data: badcases })
    const value = option.series.find((s) => s.name === '数值')
    const areas = value?.markArea?.data as Array<
      Array<{ xAxis: number; itemStyle?: { color?: string } }>
    >
    for (const area of areas) {
      expect(area[0].itemStyle?.color).toBeTruthy()
    }
  })

  it('没有 badcase 时 markArea 是空数组（不是空对象）', () => {
    const option = buildDetectionOption({ data: { ...badcases, badcases: [] } })
    const value = option.series.find((s) => s.name === '数值')
    expect(value?.markArea?.data).toEqual([])
  })

  it('三条线：数值 / 分数 / 阈值', () => {
    const option = buildDetectionOption({ data: badcases })
    expect(option.series.map((s) => s.name)).toEqual(['数值', '分数', '阈值'])
  })

  it('阈值线挂在分数轴上', () => {
    const option = buildDetectionOption({ data: badcases })
    const threshold = option.series.find((s) => s.name === '阈值')
    expect(threshold?.yAxisIndex).toBe(1)
  })

  it('分数线也挂在分数轴上', () => {
    const option = buildDetectionOption({ data: badcases })
    expect(option.series.find((s) => s.name === '分数')?.yAxisIndex).toBe(1)
  })

  // ── 基线带 ──

  it('有基线带时多画带与基线两条', () => {
    const option = buildDetectionOption({ data: withBand })
    const names = option.series.map((s) => s.name)
    expect(names).toContain('基线')
    expect(names).toContain('容忍带')
  })

  it('没有基线带时不画基线系列', () => {
    const option = buildDetectionOption({ data: badcases })
    const names = option.series.map((s) => s.name)
    expect(names).not.toContain('基线')
    expect(names).not.toContain('容忍带')
  })

  it('空数组也算「没有基线带」（后端对无带算法存空数组）', () => {
    const option = buildDetectionOption({
      data: { ...badcases, baseline: [], lower: [], upper: [] },
    })
    const names = option.series.map((s) => s.name)
    expect(names).not.toContain('基线')
    expect(names).not.toContain('容忍带')
  })

  it('⚠️ 带用 custom series 画，不用 stack', () => {
    // stack 是累加的，lower 为负时会画到 [lower+upper] 而不是 [lower, upper]
    const option = buildDetectionOption({ data: withBand })
    const band = option.series.find((s) => s.name === '容忍带')
    expect(band?.type).toBe('custom')
    expect(band?.stack).toBeUndefined()
    expect(typeof band?.renderItem).toBe('function')
  })

  it('预测区间的带标注为「预测区间」而不是「容忍带」', () => {
    const option = buildDetectionOption({
      data: { ...withBand, band_kind: 'prediction_interval' },
    })
    const names = option.series.map((s) => s.name)
    expect(names).toContain('预测区间')
    expect(names).toContain('预测基线')
    expect(names).not.toContain('容忍带')
  })

  it('图例跟着带的语义走', () => {
    const option = buildDetectionOption({ data: withBand })
    expect(option.legend?.data).toContain('基线')
    const predicted = buildDetectionOption({
      data: { ...withBand, band_kind: 'prediction_interval' },
    })
    expect(predicted.legend?.data).toContain('预测区间')
  })

  it('基线缺点断线（connectNulls 不开）', () => {
    const option = buildDetectionOption({
      data: { ...withBand, baseline: [1, null, 3, 4, 5] },
    })
    const line = option.series.find((s) => s.name === '基线')
    expect(line?.connectNulls).not.toBe(true)
  })
})

describe('badcaseLabel', () => {
  it('误报与漏报有中文名', () => {
    expect(badcaseLabel('false_positive')).toBe('误报')
    expect(badcaseLabel('false_negative')).toBe('漏报')
  })

  it('未知类型原样显示', () => {
    expect(badcaseLabel('whatever')).toBe('whatever')
  })
})
