import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PreviewPanel } from './PreviewPanel'
import type { Preview } from '../../api/types'

function preview(overrides: Partial<Preview> = {}): Preview {
  return {
    run_id: 1,
    job_id: 1,
    detector: 'iqr',
    requested_detector: 'iqr',
    metric_class: 'stationary',
    detector_rationale: '',
    detector_fallback: false,
    score_type: 'zscore',
    scale_source: 'iqr',
    status: 'ok',
    series_id: 's-1',
    group: null,
    n: 2,
    n_valid: 2,
    n_missing: 0,
    n_alerts: 0,
    n_p0: 0,
    sufficient: true,
    insufficient_reason: '',
    sampled: false,
    original_n: 2,
    timestamps: ['2026-01-01 00:00:00', '2026-01-01 00:05:00'],
    values: [1, 2],
    scores: [0, 0],
    baseline: null,
    lower: null,
    upper: null,
    severity: [0, 0],
    alert_threshold: 2.5,
    critical_threshold: 4,
    alert_rules: [],
    levels: ['正常'],
    series: [],
    ...overrides,
  }
}

function renderPanel(value: Preview) {
  return render(
    <PreviewPanel isLoading={false} error={null} preview={value} onRun={() => {}} />,
  )
}

describe('PreviewPanel 的尺度状态', () => {
  it('无法判定时给出「无法判定」标签', () => {
    renderPanel(preview({ status: 'undetermined', scale_source: 'none' }))
    expect(screen.getByText('无法判定')).toBeTruthy()
  })

  it('尺度退回标准差时给出降级标签', () => {
    renderPanel(preview({ scale_source: 'std' }))
    expect(screen.getByText('尺度降级 · std')).toBeTruthy()
  })

  it('正常尺度不显示任何提示', () => {
    renderPanel(preview())
    expect(screen.queryByText('无法判定')).toBeNull()
    expect(screen.queryByText('尺度降级 · std')).toBeNull()
  })
})
