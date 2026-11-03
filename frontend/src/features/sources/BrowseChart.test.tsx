/**
 * 浏览结果的时序图。
 *
 * ⚠️ 图画的是**原始数据** —— 没有检测分数、没有基线带。
 *    那些是「检测结果」页的东西。
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  BrowseChart,
  buildBrowseOption,
  browseChartReason,
  extractBrowseSeries,
  type BrowseChartProps,
} from './BrowseChart'

const COLUMNS = [
  { name: 'ts', type: 'TEXT' },
  { name: 'host', type: 'TEXT' },
  { name: 'value', type: 'REAL' },
]

const base: BrowseChartProps = {
  columns: COLUMNS,
  rows: [
    ['2026-10-30T00:00:00+00:00', 'web', 1],
    ['2026-10-30T00:01:00+00:00', 'web', 2],
    ['2026-10-30T00:00:00+00:00', 'db', 3],
    ['2026-10-30T00:01:00+00:00', 'db', 4],
  ],
  roles: { time_column: 'ts', value_column: 'value', group_column: 'host' },
  timeValues: [1000, 2000, 1000, 2000],
}

describe('extractBrowseSeries', () => {
  it('按分组列拆成多条线', () => {
    const series = extractBrowseSeries(base)
    expect(series.map((s) => s.name)).toEqual(['web', 'db'])
    expect(series[0].points).toEqual([
      [1000, 1],
      [2000, 2],
    ])
  })

  it('没有分组列 → 一条线，名字取自值列', () => {
    const series = extractBrowseSeries({
      ...base,
      roles: { time_column: 'ts', value_column: 'value' },
    })
    expect(series).toHaveLength(1)
    expect(series[0].name).toBe('value')
    expect(series[0].points).toHaveLength(4)
  })

  it('⚠️ 时间解析不出来的行**跳过** —— 不能画到 1970 年', () => {
    const series = extractBrowseSeries({
      ...base,
      rows: [['a', 'web', 1], ['b', 'web', 2]],
      timeValues: [null, 2000],
    })
    expect(series[0].points).toEqual([[2000, 2]])
  })

  it('值是 null → 保留成断点（不是跳过）', () => {
    const series = extractBrowseSeries({
      ...base,
      rows: [['a', 'web', 1], ['b', 'web', null]],
      timeValues: [1000, 2000],
    })
    expect(series[0].points).toEqual([
      [1000, 1],
      [2000, null],
    ])
  })

  it('没有时间列 → 空数组', () => {
    const series = extractBrowseSeries({ ...base, timeValues: null })
    expect(series).toEqual([])
  })

  it('角色指向的列不在结果里 → 空数组', () => {
    const series = extractBrowseSeries({
      ...base,
      roles: { time_column: 'ts', value_column: '不存在' },
    })
    expect(series).toEqual([])
  })
})

describe('browseChartReason', () => {
  it('正常 → null', () => {
    expect(browseChartReason(base)).toBeNull()
  })

  it('没有时间列 → no-time-column', () => {
    expect(browseChartReason({ ...base, roles: { value_column: 'value' } })).toBe(
      'no-time-column',
    )
  })

  it('没有值列 → no-value-column', () => {
    expect(browseChartReason({ ...base, roles: { time_column: 'ts' } })).toBe(
      'no-value-column',
    )
  })

  it('0 行 → no-rows', () => {
    expect(browseChartReason({ ...base, rows: [] })).toBe('no-rows')
  })

  it('⚠️ 时间一个都解析不出来 → no-parseable-time（与「没有时间列」不是一回事）', () => {
    expect(
      browseChartReason({ ...base, rows: [['a', 'web', 1]], timeValues: [null] }),
    ).toBe('no-parseable-time')
  })
})

describe('buildBrowseOption', () => {
  it('x 轴是**真时间轴** —— 类别轴会把缺采的空档压掉', () => {
    const option = buildBrowseOption(base)
    expect((option.xAxis as { type: string }).type).toBe('time')
  })

  it('y 轴不从 0 起 —— 贴着数据范围走', () => {
    const option = buildBrowseOption(base)
    const yAxis = option.yAxis as { min: number; max: number }
    // 数据是 1~4 → 边界不能切在数据外
    expect(yAxis.min).toBeLessThanOrEqual(1)
    expect(yAxis.max).toBeGreaterThanOrEqual(4)
  })

  it('⚠️ y 轴边界是「好看」的整数，不是原始值', () => {
    /* 12.0746815396624 这种原始值当刻度标签，一眼看去全是数字噪声。 */
    const option = buildBrowseOption({
      ...base,
      rows: [
        ['a', 'web', 12.0746815396624],
        ['b', 'web', 95.769080192686],
      ],
      timeValues: [1000, 2000],
    })
    const yAxis = option.yAxis as { min: number; max: number }
    expect(yAxis.min).toBe(10)
    expect(yAxis.max).toBe(100)
  })

  it('每组一条线，颜色取自调色板', () => {
    const option = buildBrowseOption(base)
    expect(option.series).toHaveLength(2)
    const colors = option.series.map((s) => s.lineStyle?.color)
    expect(colors[0]).toBeTruthy()
    expect(colors[0]).not.toBe(colors[1])
  })

  it('数据点是 [x, y] 对（时间轴要成对的坐标）', () => {
    const option = buildBrowseOption(base)
    expect(option.series[0].data).toEqual([
      [1000, 1],
      [2000, 2],
    ])
  })

  it('缺点断线 —— connectNulls 不开', () => {
    const option = buildBrowseOption(base)
    expect(option.series[0].connectNulls).not.toBe(true)
  })

  it('⚠️ 只有一个点时显示圆点 —— symbol:none 会让它隐形', () => {
    const option = buildBrowseOption({
      ...base,
      rows: [['a', 'web', 1]],
      timeValues: [1000],
    })
    expect(option.series[0].symbol).toBe('circle')
  })

  it('多个点时不显示 symbol', () => {
    const option = buildBrowseOption(base)
    expect(option.series[0].symbol).toBe('none')
  })

  it('悬停显示该时刻各系列的值（axis 触发）', () => {
    const option = buildBrowseOption(base)
    expect((option.tooltip as { trigger: string }).trigger).toBe('axis')
  })
})

describe('BrowseChart', () => {
  it('没有时间列时说明还差什么 —— 不是一片空白', () => {
    render(<BrowseChart {...base} roles={{ value_column: 'value' }} />)
    expect(screen.getByText(/指派为「时间列」/)).toBeTruthy()
  })

  it('没有值列时说明还差什么', () => {
    render(<BrowseChart {...base} roles={{ time_column: 'ts' }} />)
    expect(screen.getByText(/指派为「值列」/)).toBeTruthy()
  })

  it('0 行时说清楚是「没取到数据」', () => {
    render(<BrowseChart {...base} rows={[]} />)
    expect(screen.getByText(/没有取到数据/)).toBeTruthy()
  })

  it('时间都解析不出来时提示检查时间格式与源时区', () => {
    render(<BrowseChart {...base} rows={[['a', 'web', 1]]} timeValues={[null]} />)
    expect(screen.getByText(/时间格式/)).toBeTruthy()
  })
})
