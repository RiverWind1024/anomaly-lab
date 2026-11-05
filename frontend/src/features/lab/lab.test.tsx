/**
 * 指标预检页：结果区把「窗口质量 / 形态 / 候选算法」讲清楚。
 *
 * ⚠️ 这里只测渲染契约 —— 取数与推断的真值在后端测试里。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LabPage, ResultView } from './LabPage'
import type { LabInspectResult } from '../../api/types'

const RESULT: LabInspectResult = {
  spec: {},
  freq: '1h',
  window_points: 50,
  sampling: {
    mode: 'even',
    window_points: 50,
    stride_points: 50,
    max_points: 200,
    max_windows: 10,
    min_valid_ratio: 0.8,
    seed: 42,
  },
  period_capability: {
    daily_points: 24,
    daily_ok: false,
    weekly_points: 168,
    weekly_ok: false,
    max_period_points: 16,
  },
  series: [
    {
      series_id: 'm:a',
      group: 'a',
      n: 200,
      data_start: '2026-01-01T00:00:00+00:00',
      data_end: '2026-01-05T04:00:00+00:00',
      shape: {
        metric_class: 'periodic',
        confidence: 0.74,
        consistency: 0.75,
        candidates: ['seasonal', 'iqr'],
        n_classified: 4,
        n_windows: 4,
      },
      windows: [
        {
          index: 0,
          start: '2026-01-01T00:00:00+00:00',
          end: '2026-01-03T02:00:00+00:00',
          n: 50,
          expected: 50,
          n_missing: 0,
          missing_ratio: 0,
          zero_ratio: 0.1,
          duplicate_timestamps: 0,
          on_grid_ratio: 1,
          median_interval_s: 3600,
          min: -1,
          max: 1,
          mean: 0,
          std: 0.7,
          sufficient: true,
          insufficient_reason: null,
          classification: {
            metric_class: 'periodic',
            confidence: 0.74,
            reasons: ['周期性显著'],
            candidates: ['seasonal', 'iqr'],
            params: {},
            rationale: '周期型需要按相位分组',
          },
          classification_reason: null,
        },
        {
          index: 1,
          start: '2026-01-03T02:00:00+00:00',
          end: '2026-01-05T04:00:00+00:00',
          n: 12,
          expected: 50,
          n_missing: 38,
          missing_ratio: 0.76,
          zero_ratio: 0,
          duplicate_timestamps: 0,
          on_grid_ratio: 1,
          median_interval_s: 3600,
          min: 0,
          max: 1,
          mean: 0.5,
          std: 0.2,
          sufficient: false,
          insufficient_reason: '有效点占比 24%，低于 80%',
          classification: null,
          classification_reason: '点数不足：窗口只有 12 点，形态推断至少需要 30 点',
        },
      ],
    },
  ],
  warnings: ['共 3 条序列，按 max_series 只纳入前 2 条，其余 1 条未纳入'],
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(
        JSON.stringify({ sources: [], metrics: [], jobs: [], detectors: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderWithProviders(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ResultView', () => {
  it('展示警告、汇总、周期可识别性与窗口明细', () => {
    renderWithProviders(<ResultView result={RESULT} />)

    expect(screen.getByText(/未纳入/)).toBeInTheDocument()
    expect(screen.getByText('m:a')).toBeInTheDocument()
    expect(screen.getAllByText('周期型').length).toBeGreaterThan(0)
    expect(screen.getAllByText('季节性分组 / IQR 围栏').length).toBeGreaterThan(0)
    // 日周期 24 点、50 点窗口 → 看不到
    expect(screen.getByText(/需要 24 点/)).toBeInTheDocument()
    expect(screen.getByText('不足')).toBeInTheDocument()
  })
})

describe('LabPage', () => {
  it('初始状态给出操作提示', async () => {
    renderWithProviders(<LabPage />)

    expect(screen.getByRole('heading', { name: '指标预检' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始预检' })).toBeInTheDocument()
    expect(await screen.findByText(/默认取最近 30 天/)).toBeInTheDocument()
  })
})
