import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DetectionRecord, DetectionRecordList, RunSeriesDetail } from '../../api/types'
import { PlatformDetections } from './PlatformDetections'

/** ECharts 要 canvas，jsdom 没实现 —— 换成占位。 */
vi.mock('../jobs/PreviewChart', () => ({
  PreviewChart: () => <div data-testid="preview-chart" />,
}))

function record(extra: Partial<DetectionRecord> = {}): DetectionRecord {
  return {
    run_id: 12,
    job_id: 1,
    job_name: 'cpu-job',
    metric_id: 1,
    metric_name: 'cpu',
    source_name: 'local',
    started_at: '2026-11-06T09:00:00+00:00',
    series_id: 'cpu:web',
    group: null,
    n: 60,
    n_valid: 60,
    n_missing: 0,
    n_alerts: 3,
    n_p0: 1,
    sufficient: true,
    detector: 'iqr',
    metric_class: 'stationary',
    fallback: false,
    start_ts: '2026-11-06T08:00:00',
    end_ts: '2026-11-06T09:00:00',
    scale_source: 'iqr',
    scale_fallback: false,
    status: 'ok',
    has_decision: true,
    ...extra,
  }
}

const list: DetectionRecordList = {
  records: [record()],
  total: 1,
  limit: 20,
  offset: 0,
  jobs: [{ id: 1, name: 'cpu-job' }],
}

const detail: RunSeriesDetail = {
  run_id: 12,
  series_id: 'cpu:web',
  detector: 'iqr',
  scale_source: 'iqr',
  status: 'ok',
  scale_fallback: false,
  timestamps: ['2026-11-06T08:00:00'],
  values: [10],
  scores: [0.5],
  severity: [0],
  decision: {
    quality: { n: 60, n_missing: 0, zero_ratio: 0, n_nonzero: 60 },
    select: { detector: 'iqr', requested: 'auto', fallback: false },
    threshold: { scale_source: 'iqr', status: 'ok' },
    detect: { n_alerts: 3, n_p0: 1 },
  },
  baseline: [],
  lower: [],
  upper: [],
  alert_threshold: 2.5,
  critical_threshold: 4,
  score_type: 'zscore',
  levels: ['正常', 'P1', 'P0'],
  labels: [],
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

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/platform/detections')) return jsonResponse(list)
    if (url.startsWith('/api/runs/')) return jsonResponse(detail)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PlatformDetections />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PlatformDetections', () => {
  it('列出平台运行产生的检测记录', async () => {
    renderPanel()
    expect(await screen.findByText('cpu:web')).toBeInTheDocument()
    expect(screen.getByText('cpu-job')).toBeInTheDocument()
    expect(screen.getByText('#12')).toBeInTheDocument()
  })

  it('点一条记录 → 抽屉里能看到检测流程', async () => {
    renderPanel()
    await userEvent.click(await screen.findByText('cpu:web'))

    expect(await screen.findByText('检测流程')).toBeInTheDocument()
    // 六段里能确定的几段
    expect(screen.getByText('数据质量')).toBeInTheDocument()
    expect(screen.getByText('算法选择')).toBeInTheDocument()
    expect(screen.getByText('结果')).toBeInTheDocument()
    expect(screen.getByTestId('preview-chart')).toBeInTheDocument()
  })

  it('打开「只看有告警」会把条件带给后端', async () => {
    renderPanel()
    await screen.findByText('cpu:web')
    await userEvent.click(screen.getByRole('switch'))

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => String(call[0]))
      expect(urls.some((url) => url.includes('only_alerts=true'))).toBe(true)
    })
  })

  it('没有记录时给出下一步', async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ ...list, records: [], total: 0 }))
    renderPanel()
    expect(await screen.findByText('还没有检测记录')).toBeInTheDocument()
    expect(screen.getByText(/运行一次/)).toBeInTheDocument()
  })
})
