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
    scale_fallback: false,
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
  it('无法判定时给出「无法判定」标签，且不误报降级', () => {
    renderPanel(preview({ status: 'undetermined', scale_source: 'none' }))
    expect(screen.getByText('无法判定')).toBeTruthy()
    expect(screen.queryByText(/尺度降级/)).toBeNull()
  })

  it('真的降级时才给降级标签', () => {
    renderPanel(preview({ scale_source: 'std', scale_fallback: true }))
    expect(screen.getByText('尺度降级 · std')).toBeTruthy()
  })

  it('原生 mad 尺度不算降级 —— 不显示任何提示', () => {
    renderPanel(preview({ detector: 'mad', scale_source: 'mad', scale_fallback: false }))
    expect(screen.queryByText('无法判定')).toBeNull()
    expect(screen.queryByText(/尺度降级/)).toBeNull()
  })

  it('zscore 的原生 std 不算降级', () => {
    renderPanel(preview({ detector: 'zscore', scale_source: 'std', scale_fallback: false }))
    expect(screen.queryByText(/尺度降级/)).toBeNull()
  })
})

describe('PreviewPanel 的告警方向', () => {
  it('方向没生效时给出警告，并说明「0 告警不代表正常」', () => {
    // 配了「只报偏低」但算法没有基线 —— 告警数 0 不能当成没事
    renderPanel(preview({ alert_direction: 'below', direction_applied: false, n_alerts: 0 }))
    expect(
      screen.getByText('这个任务的算法没有基线，无法判断「只报偏低」'),
    ).toBeTruthy()
    expect(screen.getByText(/本次运行没有产生告警，不代表数据正常/)).toBeTruthy()
  })

  it('方向生效时不显示警告', () => {
    renderPanel(preview({ alert_direction: 'below', direction_applied: true }))
    expect(screen.queryByText(/无法判断「只报偏低」/)).toBeNull()
  })
})
