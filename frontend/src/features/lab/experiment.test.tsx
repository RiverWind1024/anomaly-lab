/**
 * 多算法对比面板：把「检出画像」讲清楚。
 *
 * ⚠️ 没有真值 —— 所以这里只测「检出画像」的渲染，
 *    检测本身的真值在后端测试里。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ExperimentPanel } from './ExperimentPanel'
import type { LabRunResult } from '../../api/types'

const RESULT: LabRunResult = {
  spec: {
    kind: 'metric',
    metric_id: 1,
    source_id: 1,
    sql: null,
    time_column: null,
    value_column: null,
    group_column: null,
    time_format: 'iso_utc',
    source_timezone: 'UTC',
    freq: '1h',
    missing_policy: null,
    max_series: 20,
    start: '2026-01-01T00:00:00+00:00',
    end: '2026-01-09T08:00:00+00:00',
    sampling: {
      mode: 'even',
      window_points: 100,
      stride_points: 100,
      max_points: 1000,
      max_windows: 10,
      min_valid_ratio: 0.8,
      seed: 42,
    },
    truth: 'none',
    synthetic: {
      metric_class: 'periodic',
      n_points: 1000,
      n_anomalies: 5,
      anomaly_types: [],
      seed: 42,
    },
    public: { dataset: 'nab', name: null, limit: 20 },
  },
  freq: '1h',
  window_points: 100,
  multipliers: ['1.5', '2.0', '2.5', '3.0', '3.5', '4.0'],
  primary_multiplier: '2.5',
  windows: [
    {
      series_id: 'm:a',
      index: 0,
      start: '2026-01-01T00:00:00+00:00',
      end: '2026-01-05T04:00:00+00:00',
      n: 100,
      expected: 100,
      sufficient: true,
      missing_ratio: 0,
    },
    {
      series_id: 'm:a',
      index: 1,
      start: '2026-01-05T04:00:00+00:00',
      end: '2026-01-09T08:00:00+00:00',
      n: 20,
      expected: 100,
      sufficient: false,
      missing_ratio: 0.8,
    },
  ],
  results: [
    {
      detector: 'auto',
      aggregate: {
        n_windows: 1,
        n_windows_skipped: 1,
        n_points: 100,
        n_alerts: 15,
        alert_ratio: 0.15,
        n_windows_with_alerts: 1,
        stability: 0.038,
        elapsed_ms: 4.9,
        sensitivity: { '1.5': 31, '2.0': 17, '2.5': 15, '3.0': 15, '3.5': 12, '4.0': 8 },
        resolved_mix: { seasonal: 1 },
      },
      per_window: [
        {
          series_id: 'm:a',
          window_index: 0,
          detector: 'seasonal',
          requested: 'auto',
          metric_class: 'periodic',
          fallback: false,
          rationale: '周期型需要按相位分组',
          n: 100,
          n_alerts: 15,
          alert_ratio: 0.15,
          elapsed_ms: 4.9,
          sensitivity: { '1.5': 31, '2.5': 15 },
          skipped: false,
          skip_reason: null,
        },
        {
          series_id: 'm:a',
          window_index: 1,
          detector: 'auto',
          requested: 'auto',
          metric_class: null,
          fallback: false,
          rationale: '',
          n: 20,
          n_alerts: 0,
          alert_ratio: 0,
          elapsed_ms: 0,
          sensitivity: {},
          skipped: true,
          skip_reason: '有效点占比 20%，低于 80%',
        },
      ],
    },
    {
      detector: 'zscore',
      aggregate: {
        n_windows: 1,
        n_windows_skipped: 1,
        n_points: 100,
        n_alerts: 7,
        alert_ratio: 0.07,
        n_windows_with_alerts: 1,
        stability: 0.026,
        elapsed_ms: 0.3,
        sensitivity: { '1.5': 10, '2.0': 10, '2.5': 7, '3.0': 4, '3.5': 0, '4.0': 0 },
        resolved_mix: { zscore: 1 },
      },
      per_window: [
        {
          series_id: 'm:a',
          window_index: 0,
          detector: 'zscore',
          requested: 'zscore',
          metric_class: null,
          fallback: false,
          rationale: '',
          n: 100,
          n_alerts: 7,
          alert_ratio: 0.07,
          elapsed_ms: 0.3,
          sensitivity: { '1.5': 10, '2.5': 7 },
          skipped: false,
          skip_reason: null,
        },
        {
          series_id: 'm:a',
          window_index: 1,
          detector: 'zscore',
          requested: 'zscore',
          metric_class: null,
          fallback: false,
          rationale: '',
          n: 20,
          n_alerts: 0,
          alert_ratio: 0,
          elapsed_ms: 0,
          sensitivity: {},
          skipped: true,
          skip_reason: '有效点占比 20%，低于 80%',
        },
      ],
    },
  ],
  warnings: [],
}

function renderWithProviders(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ExperimentPanel', () => {
  it('对比表列出每个算法的检出画像', () => {
    renderWithProviders(<ExperimentPanel result={RESULT} />)

    expect(screen.getByRole('heading', { name: '算法对比' })).toBeInTheDocument()
    // 两个算法各一行（表格里同时有中文标签与原始名）
    expect(screen.getAllByText('自动推荐').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Z 分数').length).toBeGreaterThan(0)
    // 检出率与耗时
    expect(screen.getByText('15.00%')).toBeInTheDocument()
    expect(screen.getByText('7.00%')).toBeInTheDocument()
    expect(screen.getByText('4.9 ms')).toBeInTheDocument()
    // auto 实际用的算法分布
    expect(screen.getByText('季节性分组×1')).toBeInTheDocument()
  })

  it('逐窗明细标出 auto 每一窗实际用的算法', () => {
    renderWithProviders(<ExperimentPanel result={RESULT} />)

    expect(screen.getByRole('heading', { name: '逐窗明细' })).toBeInTheDocument()
    expect(screen.getAllByText(/季节性分组/).length).toBeGreaterThan(0)
    // 数据不足的窗口显示「跳过」而不是 0（每个检测器一列，所以有多处）
    expect(screen.getAllByText('跳过').length).toBeGreaterThan(0)
  })

  it('倍数敏感性图有标题', () => {
    renderWithProviders(<ExperimentPanel result={RESULT} />)

    expect(screen.getByRole('heading', { name: '倍数敏感性' })).toBeInTheDocument()
  })
})
