import { describe, expect, it } from 'vitest'
import type { RunSummary, SeriesEntry } from '../../api/types'
import { formatRunOption, formatSeriesOption } from './RunsView'

const run = (over: Partial<RunSummary> = {}): RunSummary => ({
  id: 7,
  job_id: 1,
  status: 'success',
  n_series: 3,
  n_alerts: 12,
  error: null,
  started_at: '2026-10-30T02:00:00+00:00',
  finished_at: '2026-10-30T02:00:01+00:00',
  ...over,
})

const series = (over: Partial<SeriesEntry> = {}): SeriesEntry => ({
  series_id: 'demo-1',
  group: null,
  n: 100,
  n_valid: 98,
  n_missing: 2,
  n_alerts: 5,
  n_p0: 1,
  sufficient: true,
  detector: 'seasonal',
  metric_class: 'periodic',
  fallback: false,
  file: null,
  ...over,
})

describe('formatRunOption', () => {
  it('文案照搬旧版：#id status (n 序列 / n 告警)', () => {
    expect(formatRunOption(run())).toBe('#7 success (3 序列 / 12 告警)')
  })

  it('失败时追加错误原因的前 40 字', () => {
    const text = formatRunOption(run({ status: 'failed', error: 'x'.repeat(80) }))
    expect(text).toContain('failed')
    expect(text.endsWith(' · ' + 'x'.repeat(40))).toBe(true)
  })

  it('错误原因短于 40 字时全量显示', () => {
    expect(formatRunOption(run({ error: 'boom' }))).toBe(
      '#7 success (3 序列 / 12 告警) · boom',
    )
  })

  it('没有错误时不追加后缀', () => {
    expect(formatRunOption(run())).not.toContain('·')
  })
})

describe('formatSeriesOption', () => {
  it('正常序列显示告警数', () => {
    expect(formatSeriesOption(series())).toBe('demo-1 (5 告警)')
  })

  it('数据不足的序列显示「数据不足」而不是告警数', () => {
    expect(formatSeriesOption(series({ sufficient: false, n_alerts: 0 }))).toBe(
      'demo-1 (数据不足)',
    )
  })
})
