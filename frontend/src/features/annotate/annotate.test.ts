import { describe, expect, it } from 'vitest'
import type { Annotation, SeriesValues } from '../../api/types'
import { ANOMALY_TYPES, buildAnnotateOption } from './AnnotatePage'

const data: SeriesValues = {
  series_id: 'demo-1',
  timestamps: ['t0', 't1', 't2', 't3'],
  values: [1, 2, 3, 4],
  labels: [0, 0, 1, 0],
}

const annotation = (over: Partial<Annotation> = {}): Annotation => ({
  series_id: 'demo-1',
  start: 1,
  end: 2,
  type: 'spike',
  created_at: '2026-10-30T00:00:00+00:00',
  ...over,
})

describe('ANOMALY_TYPES', () => {
  it('固定 6 种，与旧 prompt 弹窗的提示文案一致', () => {
    expect(ANOMALY_TYPES.map((t) => t.value)).toEqual([
      'spike',
      'contextual',
      'drift',
      'freq_shift',
      'variance_shift',
      'flatline',
    ])
  })
})

describe('buildAnnotateOption', () => {
  it('波形是一条线', () => {
    const option = buildAnnotateOption({ data, annotations: [], onBrush: () => {} })
    expect(option.series[0].type).toBe('line')
    expect(option.series[0].data).toEqual(data.values)
  })

  it('已有标注画成 markArea', () => {
    const option = buildAnnotateOption({
      data,
      annotations: [annotation({ start: 1, end: 2 })],
      onBrush: () => {},
    })
    const areas = option.series[0].markArea?.data as Array<Array<{ xAxis: number }>>
    expect(areas).toHaveLength(1)
    expect(areas[0][0].xAxis).toBe(1)
    expect(areas[0][1].xAxis).toBe(2)
  })

  it('没有标注时 markArea 是空数组（不画区间，但结构在）', () => {
    const option = buildAnnotateOption({ data, annotations: [], onBrush: () => {} })
    expect(option.series[0].markArea?.data).toEqual([])
  })

  it('刷选只作用在 x 轴、单选', () => {
    const option = buildAnnotateOption({ data, annotations: [], onBrush: () => {} })
    expect(option.brush?.xAxisIndex).toBe(0)
    expect(option.brush?.brushMode).toBe('single')
  })

  it('dataZoom 同时有 inside 与 slider', () => {
    const option = buildAnnotateOption({ data, annotations: [], onBrush: () => {} })
    expect(option.dataZoom?.length).toBe(2)
  })

  it('x 轴是时间戳的 category 轴', () => {
    const option = buildAnnotateOption({ data, annotations: [], onBrush: () => {} })
    expect(option.xAxis).toMatchObject({ type: 'category', data: data.timestamps })
  })
})
