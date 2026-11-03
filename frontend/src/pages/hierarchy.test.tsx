/**
 * 层级下钻：数据源 → 指标 → 序列。
 *
 * ⚠️ 这三层是从属关系 —— 侧边栏「数据」是分组，
 *    下面挂「数据源」与「指标」两个平级页面。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceDetailPage } from './SourceDetailPage'
import { SourcesPage } from './SourcesPage'
import { MetricDetailPage } from './MetricDetailPage'
import { MetricFormPage } from './MetricFormPage'
import {
  PREVIEW_STORAGE_KEY,
  writePreviewPayload,
  type PreviewPayload,
} from '../features/metrics/previewBridge'

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

const QUERY_RESULT = {
  columns: [
    // ⚠️ 列名故意跟表单默认值（ts / value）不一样 ——
    //    否则「预填生效」与「默认值」分不开，测试就是假的
    { name: 'observed_at', type: 'TIMESTAMP' },
    { name: 'metric_value', type: 'REAL' },
  ],
  rows: [['2026-10-30T09:00:00+00:00', 3.5]],
  total: 1,
  truncated: false,
  elapsed_ms: 7,
}

let calls: string[] = []

/**
 * 模拟预览页把配置带回来。
 *
 * ⚠️ 预览页开在新标签页里，靠 localStorage + storage 事件回传 ——
 *    这里直接派发事件，测的是「收到之后表单怎么被预填」。
 */
function sendPreviewMessage(payload: PreviewPayload) {
  writePreviewPayload(payload)
  window.dispatchEvent(
    new StorageEvent('storage', {
      key: PREVIEW_STORAGE_KEY,
      newValue: window.localStorage.getItem(PREVIEW_STORAGE_KEY),
    }),
  )
}

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
      if (url.includes('/api/platform/sources/1/query')) {
        return new Response(JSON.stringify(QUERY_RESULT), {
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
    // ⚠️ 「demo-metric」出现两处 —— 指标表里一次，任务表的「指标」列里一次
    await waitFor(() => expect(screen.getAllByText('demo-metric').length).toBeGreaterThan(0))
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

  it('不再挂数据浏览器 —— 浏览数据在指标的编辑流程里', async () => {
    renderPage('/sources/1', '/sources/:sourceId', <SourceDetailPage />)
    await waitFor(() => expect(screen.getAllByText('demo-metric').length).toBeGreaterThan(0))
    // ⚠️ 浏览数据是「写 SQL 时看结果」的工具 ——
    //    放在数据源页上只是个孤立的功能块
    expect(screen.queryByPlaceholderText(/SELECT/)).toBeNull()
    expect(screen.queryByText('浏览数据')).toBeNull()
  })

  it('「新增指标」跳独立页面，不弹窗', async () => {
    renderPage('/sources/1', '/sources/:sourceId', <SourceDetailPage />)
    const link = await screen.findByRole('link', { name: '新增指标' })
    // ⚠️ 带 source_id —— 新页要知道给哪个数据源建指标
    expect(link.getAttribute('href')).toBe('/metrics/new?source_id=1')
  })

  it('数据源**列表页**不再展示指标列表', async () => {
    renderPage('/sources', '/sources', <SourcesPage />)
    await waitFor(() => expect(screen.getByText('demo-sqlite')).toBeTruthy())
    // ⚠️ 指标搬到独立页面（「数据 › 指标」）——
    //    一个页面讲一件事，两个都塞进来列表页就没法看了
    const headings = [...document.querySelectorAll('h2')].map((h) => h.textContent)
    expect(headings).not.toContain('指标')
  })

  it('数据源**详情页**仍然展示该源下的指标', async () => {
    renderPage('/sources/1', '/sources/:sourceId', <SourceDetailPage />)
    await waitFor(() => expect(screen.getAllByText('demo-metric').length).toBeGreaterThan(0))
    // ⚠️ 从属关系该有的样子 —— 详情页看得到「这个源下有哪些指标」
    const headings = [...document.querySelectorAll('h2')].map((h) => h.textContent)
    expect(headings).toContain('指标')
  })
})

describe('MetricFormPage', () => {
  it('新增时带上数据源预填', async () => {
    renderPage('/metrics/new?source_id=1', '/metrics/new', <MetricFormPage />)
    // ⚠️ antd 的 Select 不把值放在 input.value 上 ——
    //    它渲染成 `.ant-select-selection-item` 的文本
    await waitFor(() => {
      const selected = document.querySelector('.ant-select-selection-item')
      expect(selected?.textContent).toContain('demo-sqlite')
    })
  })

  it('预览页带回的配置会预填指标表单', async () => {
    renderPage('/metrics/new?source_id=1', '/metrics/new', <MetricFormPage />)
    await waitFor(() => expect(screen.getByLabelText('名称')).toBeTruthy())
    act(() => {
      sendPreviewMessage({
        sourceId: 1,
        sql: 'SELECT observed_at, metric_value FROM t WHERE $timefilter',
        columns: QUERY_RESULT.columns,
        time_column: 'observed_at',
        value_column: 'metric_value',
        group_column: undefined,
        time_format: 'iso_utc',
      })
    })

    // 列名从预览结果里带过来
    await waitFor(() => {
      expect((screen.getByLabelText('时间列') as HTMLInputElement).value).toBe('observed_at')
    })
    expect((screen.getByLabelText('值列') as HTMLInputElement).value).toBe('metric_value')
  })

  it('带回的 SQL 不含 $timefilter 时不预填查询语句', async () => {
    renderPage('/metrics/new?source_id=1', '/metrics/new', <MetricFormPage />)
    await waitFor(() => expect(screen.getByLabelText('名称')).toBeTruthy())
    act(() => {
      sendPreviewMessage({
        sourceId: 1,
        sql: 'SELECT observed_at, metric_value FROM t LIMIT 100',
        columns: QUERY_RESULT.columns,
        time_column: 'observed_at',
        value_column: 'metric_value',
        group_column: undefined,
        time_format: 'iso_utc',
      })
    })

    // ⚠️ 指标要求恰好一个 $timefilter —— 预填非法 SQL 会让用户白填一遍
    await waitFor(() => {
      expect((screen.getByLabelText('查询语句') as HTMLTextAreaElement).value).toContain(
        '$timefilter',
      )
    })
    expect((screen.getByLabelText('查询语句') as HTMLTextAreaElement).value).not.toContain(
      'LIMIT 100',
    )
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
