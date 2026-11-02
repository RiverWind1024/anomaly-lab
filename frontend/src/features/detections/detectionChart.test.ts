import { describe, expect, it } from 'vitest'
import type { Badcases } from '../../api/types'
import { badcaseLabel, buildDetectionOption, toRanges } from './detectionChart'

const badcases: Badcases = {
  series_id: 'demo-1',
  detector: 'iqr',
  threshold: 2.5,
  score_type: 'zscore',
  timestamps: ['t0', 't1', 't2', 't3', 't4'],
  values: [1, 2, 3, 4, 5],
  scores: [0.1, 0.2, 3.1, 0.4, 0.5],
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

describe('buildDetectionOption', () => {
  it('⚠️ 用 badcases[].indices 真正画出异常区间（旧版是空对象 markArea，等于没画）', () => {  // taste-skill-ignore
    const option = buildDetectionOption({ data: badcases })
    const areas = option.series[0].markArea?.data as Array<Array<{ xAxis: number }>>
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
    const areas = option.series[0].markArea?.data as Array<
      Array<{ xAxis: number; itemStyle?: { color?: string } }>
    >
    for (const area of areas) {
      expect(area[0].itemStyle?.color).toBeTruthy()
    }
  })

  it('没有 badcase 时 markArea 是空数组（不是空对象）', () => {
    const option = buildDetectionOption({ data: { ...badcases, badcases: [] } })
    expect(option.series[0].markArea?.data).toEqual([])
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
