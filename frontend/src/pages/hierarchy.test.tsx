/**
 * 层级下钻：数据源 → 指标 → 序列。
 *
 * ⚠️ 这三层是从属关系，不该平铺成同级页面 ——
 *    侧边栏只留「数据源」，指标与序列靠页面内下钻。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceDetailPage } from './SourceDetailPage'
import { MetricDetailPage } from './MetricDetailPage'

const CATALOG = {
  sources: [
    {
      id: 1,
      name: 'demo-sqlite',
      kind: 'sqlite',
      path: 'platform/source.db',
      created_at: '2026-10-30T00:00:00+00:00',
    },
  ],
  metrics: [
    {
      id: 5,
      source_id: 1,
      name: 'demo-metric',
      query: 'SELECT ts, value FROM t WHERE $timefilter',
      time_column: 'ts',
      value_column: 'value',
      group_column: 'host',
      time_format: 'iso_utc',
      freq: '5min',
      source_timezone: 'UTC',
      missing_policy: 'drop',
      created_at: '2026-10-30T00:00:00+00:00',
    },
  ],
  jobs: [
    {
      id: 7,
      metric_id: 5,
      name: 'demo-job',
      detector: 'iqr',
      alert_threshold: 2.5,
      critical_threshold: 3.75,
      window_points: 300,
      interval_seconds: 300,
      enabled: true,
      last_run_at: null,
      next_run_at: null,
      created_at: '2026-10-30T00:00:00+00:00',
      alert_rules: [],
    },
  ],
  detectors: [],
}

const PREVIEW = {
  run_id: 2,
  job_id: 7,
  detector: 'iqr',
  requested_detector: 'iqr',
  metric_class: 'periodic',
  detector_rationale: '',
  detector_fallback: false,
  score_type: 'zscore',
  series_id: 'demo-metric:web-api',
  group: 'web-api',
  n: 100,
  n_valid: 100,
  n_missing: 0,
  n_alerts: 3,
  n_p0: 1,
  sufficient: true,
  insufficient_reason: '',
  sampled: false,
  original_n: 100,
  timestamps: ['2026-01-01T00:00:00'],
  values: [1],
  scores: [0.1],
  baseline: null,
  lower: null,
  upper: null,
  severity: [0],
  alert_threshold: 2.5,
  critical_threshold: 3.75,
  alert_rules: [],
  levels: ['正常'],
  series: [
    {
      series_id: 'demo-metric:web-api',
      group: 'web-api',
      n: 100,
      n_valid: 100,
      n_missing: 0,
      n_alerts: 3,
      n_p0: 1,
      sufficient: true,
      detector: 'iqr',
      metric_class: 'periodic',
      fallback: false,
      file: null,
    },
  ],
}

let calls: string[] = []

function renderPage(path: string, routePath: string, element: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePath} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      if (url.includes('/api/platform/catalog')) {
        return new Response(JSON.stringify(CATALOG), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/api/platform/jobs/7/preview')) {
        return new Response(JSON.stringify(PREVIEW), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ detail: '没有数据' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('SourceDetailPage', () => {
  it('列出这个数据源下的指标', async () => {
    renderPage('/sources/1', '/sources/:sourceId', <SourceDetailPage />)
    expect(await screen.findByText('demo-metric')).toBeTruthy()
  })

  it('指标名链到指标详情', async () => {
    renderPage('/sources/1', '/sources/:sourceId', <SourceDetailPage />)
    const link = await screen.findByRole('link', { name: 'demo-metric' })
    expect(link.getAttribute('href')).toBe('/metrics/5')
  })

  it('数据源不存在时给出提示', async () => {
    renderPage('/sources/99', '/sources/:sourceId', <SourceDetailPage />)
    expect(await screen.findByText('数据源不存在或已被删除')).toBeTruthy()
  })
})

describe('MetricDetailPage', () => {
  it('展示指标配置', async () => {
    renderPage('/metrics/5', '/metrics/:metricId', <MetricDetailPage />)
    await waitFor(() => {
      expect((screen.getByLabelText(/名称/) as HTMLInputElement).value).toBe('demo-metric')
    })
  })

  it('列出用这个指标的检测任务', async () => {
    renderPage('/metrics/5', '/metrics/:metricId', <MetricDetailPage />)
    expect(await screen.findByRole('link', { name: 'demo-job' })).toBeTruthy()
  })

  it('列出该任务跑出的序列', async () => {
    renderPage('/metrics/5', '/metrics/:metricId', <MetricDetailPage />)
    expect(await screen.findByText('demo-metric:web-api')).toBeTruthy()
  })

  it('序列链到任务的检测结果页', async () => {
    renderPage('/metrics/5', '/metrics/:metricId', <MetricDetailPage />)
    const link = await screen.findByRole('link', { name: 'demo-metric:web-api' })
    expect(link.getAttribute('href')).toBe('/jobs/7/detections?series_id=demo-metric%3Aweb-api')
  })

  it('指标不存在时给出提示', async () => {
    renderPage('/metrics/99', '/metrics/:metricId', <MetricDetailPage />)
    expect(await screen.findByText('指标不存在或已被删除')).toBeTruthy()
  })
})
