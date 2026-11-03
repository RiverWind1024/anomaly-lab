/**
 * 指标预览页 —— 选源、选指标、看图。
 *
 * ⚠️ 重点守「指标能反推数据源」：
 *    从指标列表点「预览」过来时，URL 里只有 `metricId` ——
 *    不反推的话源是空的，指标下拉就是空的，页面显示「还没选指标」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { MetricChartPage } from './MetricChartPage'

vi.mock('../features/metrics/MetricChartPanel', () => ({
  MetricChartPanel: (props: { windowPoints: number; freq: string }) => (
    <div data-testid="chart-panel">
      {props.windowPoints}/{props.freq}
    </div>
  ),
}))

const CATALOG = {
  sources: [
    { id: 1, name: 'demo-sqlite', kind: 'sqlite', path: '', created_at: '', config: {} },
    { id: 2, name: 'mock-tsdb', kind: 'http', path: '', created_at: '', config: {} },
  ],
  metrics: [
    {
      id: 5,
      source_id: 2,
      name: 'traffic',
      query: 'SELECT ts, value FROM t WHERE $timefilter',
      time_column: 'ts',
      value_column: 'value',
      group_column: null,
      time_format: 'iso_utc',
      freq: '1min',
      source_timezone: 'UTC',
      missing_policy: 'drop',
      created_at: '',
    },
  ],
  jobs: [
    {
      id: 9,
      metric_id: 5,
      name: 'job',
      detector: 'iqr',
      alert_threshold: 2.5,
      critical_threshold: 4,
      window_points: 120,
      interval_seconds: 60,
      enabled: true,
      last_run_at: null,
      next_run_at: null,
      created_at: '',
      alert_rules: [],
    },
  ],
}

function renderPage(search = '') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/metrics/preview${search}`]}>
        <Routes>
          <Route path="/metrics/preview" element={<MetricChartPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify(CATALOG), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MetricChartPage', () => {
  it('⚠️ 只有 metricId 时，**反推出数据源**并直接显示图', async () => {
    renderPage('?metricId=5')

    await waitFor(() => {
      expect(screen.getByTestId('chart-panel')).toBeTruthy()
    })
    // 源名应该在数据源下拉里
    expect(screen.getByText(/mock-tsdb/)).toBeTruthy()
  })

  it('⚠️ 窗口点数跟着**告警任务**走', async () => {
    renderPage('?metricId=5')
    await waitFor(() => {
      expect(screen.getByTestId('chart-panel')).toBeTruthy()
    })
    // 任务里是 120 点 —— 不是默认的 60
    expect(screen.getByTestId('chart-panel').textContent).toContain('120')
  })

  it('什么都没选 → 说清楚要选什么', async () => {
    renderPage('')
    await waitFor(() => {
      expect(screen.getByText(/先选数据源，再选指标/)).toBeTruthy()
    })
  })
})
