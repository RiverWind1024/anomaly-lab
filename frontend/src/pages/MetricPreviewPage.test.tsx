/**
 * 指标取数预览页。
 *
 * ⚠️ 这一页是「写 SQL 时能立刻看到结果」的地方 ——
 *    它住在指标的新增/编辑流程里，不占数据源详情页的位置。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MetricPreviewPage } from './MetricPreviewPage'
import { PREVIEW_STORAGE_KEY, readPreviewPayload } from '../features/metrics/previewBridge'

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
  jobs: [],
  detectors: [],
}

const QUERY_RESULT = {
  columns: [
    { name: 'observed_at', type: 'TIMESTAMP' },
    { name: 'metric_value', type: 'REAL' },
  ],
  rows: [['2026-10-30T09:00:00+00:00', 3.5]],
  total: 1,
  truncated: false,
  elapsed_ms: 7,
}

let calls: string[] = []

function renderPage(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/metric-preview" element={<MetricPreviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push(url)
      if (url.includes('/api/platform/catalog')) {
        return new Response(JSON.stringify(CATALOG), {
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
      if (url.includes('/api/platform/metrics/5') && init?.method === 'PUT') {
        return new Response(JSON.stringify(CATALOG.metrics[0]), {
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

describe('MetricPreviewPage', () => {
  it('用地址里的 SQL 初始化编辑器', async () => {
    renderPage('/metric-preview?sourceId=1&sql=SELECT%20a%20FROM%20t')
    await waitFor(() => {
      expect((screen.getByPlaceholderText(/SELECT/) as HTMLTextAreaElement).value).toBe(
        'SELECT a FROM t',
      )
    })
  })

  it('执行查询后显示结果与列', async () => {
    const user = userEvent.setup({ delay: null, pointerEventsCheck: 0 })
    renderPage('/metric-preview?sourceId=1&sql=SELECT%20a%20FROM%20t')
    await user.click(await screen.findByRole('button', { name: /执\s*行/ }))

    // ⚠️ antd 的表格会额外渲染一张隐藏表来量列宽 —— 列名不止出现一次
    await waitFor(() => expect(screen.getAllByText('observed_at').length).toBeGreaterThan(0))
    expect(screen.getAllByText('metric_value').length).toBeGreaterThan(0)
    expect(calls.some((url) => url.includes('/api/platform/sources/1/query'))).toBe(true)
  })

  it('编辑指标时能把改好的配置存回指标', async () => {
    const user = userEvent.setup({ delay: null, pointerEventsCheck: 0 })
    renderPage('/metric-preview?sourceId=1&metricId=5&sql=SELECT%20ts%2C%20value%20FROM%20t')
    await user.click(await screen.findByRole('button', { name: /执\s*行/ }))

    const save = await screen.findByRole('button', { name: /保存到指标/ })
    // ⚠️ 没跑过查询就没有列角色可存 —— 按钮先禁用
    await waitFor(() => expect((save as HTMLButtonElement).disabled).toBe(false))
    await user.click(save)

    await waitFor(() => {
      const put = calls.find((url) => url.includes('/api/platform/metrics/5'))
      expect(put).toBeTruthy()
    })
  })

  it('新增指标时把配置带回原表单', async () => {
    const user = userEvent.setup({ delay: null, pointerEventsCheck: 0 })
    renderPage('/metric-preview?sourceId=1&sql=SELECT%20a%20FROM%20t')
    await user.click(await screen.findByRole('button', { name: /执\s*行/ }))
    await user.click(await screen.findByRole('button', { name: '带回表单' }))

    // ⚠️ 回传走 localStorage —— 原页面靠 storage 事件接
    await waitFor(() => {
      expect(window.localStorage.getItem(PREVIEW_STORAGE_KEY)).toBeTruthy()
    })
    const payload = readPreviewPayload(window.localStorage.getItem(PREVIEW_STORAGE_KEY))
    expect(payload?.time_column).toBe('observed_at')
    expect(payload?.value_column).toBe('metric_value')
  })

  it('列指派能带回去（分组列）', async () => {
    const user = userEvent.setup({ delay: null, pointerEventsCheck: 0 })
    renderPage('/metric-preview?sourceId=1&sql=SELECT%20a%20FROM%20t')
    await user.click(await screen.findByRole('button', { name: /执\s*行/ }))

    // ⚠️ 列头下拉决定这一列扮演什么角色
    const headerRow = within(screen.getByRole('table')).getAllByRole('row')[0]
    const select = within(headerRow).getAllByTitle('observed_at 列的角色')[0]
    await user.click(within(select).getByRole('combobox'))
    await user.click(await screen.findByTitle('分组列'))

    await user.click(await screen.findByRole('button', { name: '带回表单' }))
    await waitFor(() => {
      expect(window.localStorage.getItem(PREVIEW_STORAGE_KEY)).toBeTruthy()
    })
    const payload = readPreviewPayload(window.localStorage.getItem(PREVIEW_STORAGE_KEY))
    expect(payload?.group_column).toBe('observed_at')
  })
})
