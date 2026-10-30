import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PreviewChart, buildPreviewOption } from './PreviewChart'

const base = {
  timestamps: ['2026-10-27T22:49:00', '2026-10-27T22:54:00', '2026-10-27T22:59:00'],
  values: [1, 2, 3] as (number | null)[],
  scores: [0.1, 0.2, 0.3] as (number | null)[],
  baseline: [1, 2, 3] as (number | null)[],
  lower: [0, 1, 2] as (number | null)[],
  upper: [2, 3, 4] as (number | null)[],
  severity: [0, 0, 0],
  alertThreshold: 2.5,
  criticalThreshold: 4,
  levels: ['正常', 'P1', 'P0'],
}

describe('PreviewChart', () => {
  it('没有基线带时给出说明而不是空图', () => {
    render(<PreviewChart {...base} baseline={null} lower={null} upper={null} />)
    expect(screen.getByText(/未提供基线带/)).toBeTruthy()
  })

  it('缺点在图上表现为断线（connectNulls 不开）', () => {
    const option = buildPreviewOption({ ...base, values: [1, null, 3] })
    const series = option.series
    const valueSeries = series.find((s) => s.name === '数值')
    expect(valueSeries).toBeTruthy()
    expect(valueSeries!.connectNulls).not.toBe(true)
  })

  it('有基线带时画出下界/基线/数值/分数四条线', () => {
    const option = buildPreviewOption(base)
    const names = option.series.map((s) => s.name)
    expect(names).toContain('基线')
    expect(names).toContain('数值')
    expect(names).toContain('分数')
    expect(names.some((n) => n?.includes('界'))).toBe(true)
  })

  it('无基线带时不画基线与界带', () => {
    const option = buildPreviewOption({ ...base, baseline: null, lower: null, upper: null })
    const names = option.series.map((s) => s.name)
    expect(names).not.toContain('基线')
    expect(names.some((n) => n?.includes('界'))).toBe(false)
    // 数值与分数仍然要有 —— 没有基线不等于没数据
    expect(names).toContain('数值')
    expect(names).toContain('分数')
  })

  it('P1 / P0 告警点分成两个 scatter 系列', () => {
    const option = buildPreviewOption({
      ...base,
      severity: [0, 1, 2],
      values: [1, 2, 3],
    })
    const scatters = option.series.filter((s) => s.type === 'scatter')
    expect(scatters).toHaveLength(2)
    // P0 的点更大 —— 分级可辨
    const sizes = scatters.map((s) => s.symbolSize ?? 0)
    expect(Math.max(...sizes)).toBeGreaterThan(Math.min(...sizes))
  })

  it('null 值的点不进入告警散点', () => {
    const option = buildPreviewOption({
      ...base,
      severity: [1, 1, 1],
      values: [1, null, 3],
    })
    const p1 = option.series.find((s) => s.type === 'scatter')
    expect((p1?.data as unknown[]).length).toBe(2)
  })

  it('dataZoom 同时有 inside 与 slider（旧版有，最容易丢）', () => {
    const option = buildPreviewOption(base)
    expect(option.dataZoom?.length).toBe(2)
    const kinds = option.dataZoom?.map((z) => (z as { type: string }).type)
    expect(kinds).toContain('inside')
    expect(kinds).toContain('slider')
  })

  it('阈值线挂在分数轴上（yAxisIndex 1）', () => {
    const option = buildPreviewOption(base)
    const markLine = option.series.find((s) => s.name === '阈值')
    expect(markLine).toBeTruthy()
    expect(markLine!.yAxisIndex).toBe(1)
  })
})
