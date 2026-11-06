import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Observability } from '../../api/types'
import { MonitoringPage } from './MonitoringPage'

/** ECharts 要 canvas，jsdom 没实现 —— 换成占位。 */
vi.mock('./MonitoringChart', () => ({
  MonitoringChart: () => <div data-testid="monitoring-chart" />,
}))

const data: Observability = {
  service: {
    service_name: 'anomaly-lab',
    pid: 1234,
    started_at: '2026-11-06T10:00:00+00:00',
    uptime_seconds: 372,
    otel_enabled: false,
    otel_endpoint: '',
    sampler_running: true,
    snapshot_at: '2026-11-06T10:06:00+00:00',
  },
  interval_seconds: 60,
  current: {
    cpu_percent: 4.2,
    memory_mb: 120.5,
    db_bytes: 2048,
    runs_bytes: 4096,
    runs_count: 12,
    inflight: 1,
    due_jobs: 0,
  },
  timeline: [
    {
      at: '2026-11-06T10:05:00+00:00',
      requests: 10,
      errors: 0,
      runs: 1,
      failed_runs: 0,
      insufficient_runs: 0,
      alerts: 2,
      p0: 0,
      p50_ms: 3,
      p95_ms: 10,
      p99_ms: 20,
      cpu_percent: 3.1,
      memory_mb: 118,
      db_bytes: 2048,
      runs_bytes: 4096,
      runs_count: 12,
    },
    {
      at: '2026-11-06T10:06:00+00:00',
      requests: 12,
      errors: 1,
      runs: 0,
      failed_runs: 0,
      insufficient_runs: 0,
      alerts: 0,
      p0: 0,
      p50_ms: 3,
      p95_ms: 12,
      p99_ms: 25,
      cpu_percent: 4.2,
      memory_mb: 120.5,
      db_bytes: 2048,
      runs_bytes: 4096,
      runs_count: 12,
    },
  ],
  http: {
    total: 22,
    errors: 1,
    routes: [
      {
        method: 'GET',
        route: '/api/platform/observability',
        count: 22,
        errors: 1,
        avg_ms: 4.1,
        p95_ms: 10,
      },
    ],
  },
  alerts: { total: 2, p0: 0 },
  detectors: [
    {
      detector: 'iqr',
      calls: 12,
      fallbacks: 1,
      errors: 0,
      avg_ms: 0.2,
      p95_ms: 0.5,
      p99_ms: 1,
    },
  ],
  jobs: [
    { job: 'cpu-job', runs: 3, failed: 0, insufficient: 1, avg_ms: 800, p95_ms: 1200 },
  ],
  stages: [{ stage: 'load', count: 3, avg_ms: 120, p95_ms: 200 }],
  scheduler: {
    alive: true,
    ticks: 120,
    avg_tick_ms: 1.2,
    p95_tick_ms: 3,
    due_jobs: 0,
    last_tick_at: '2026-11-06T10:06:00+00:00',
    avg_prune_ms: null,
  },
  otel: { enabled: false, endpoint: '', hint: '未配置 ANOMALY_OTEL_ENDPOINT' },
}

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => body,
    headers: { get: () => null },
  } as unknown as Response
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse(data)),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MonitoringPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MonitoringPage', () => {
  it('展示服务状态与关键计数', async () => {
    renderPage()

    expect(await screen.findByText('6 分 12 秒')).toBeInTheDocument()
    expect(screen.getByText('运行中')).toBeInTheDocument()
    expect(screen.getByText(/次 tick/)).toBeInTheDocument()
    expect(screen.getByText('接口请求')).toBeInTheDocument()
  })

  it('有一条曲线时渲染图表', async () => {
    renderPage()
    await screen.findByText('流量与错误')
    expect(screen.getAllByTestId('monitoring-chart')).toHaveLength(4)
  })

  it('算法与任务的回退、数据不足要能看出来', async () => {
    renderPage()
    expect(await screen.findByText('IQR 围栏')).toBeInTheDocument()
    expect(screen.getByText('任务执行')).toBeInTheDocument()
    expect(screen.getByText('cpu-job')).toBeInTheDocument()
    // 回退 1 次、数据不足 1 次
    expect(screen.getAllByText('1').length).toBeGreaterThan(0)
  })

  it('OTel 未启用时给出开启方式，而不是静默', async () => {
    renderPage()
    expect(await screen.findByText('指标目前只在本机。')).toBeInTheDocument()
    expect(screen.getByText(/ANOMALY_OTEL_ENDPOINT/)).toBeInTheDocument()
  })
})
