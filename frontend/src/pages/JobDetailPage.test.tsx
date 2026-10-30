/**
 * 任务详情页：任务不存在时的表现。
 *
 * ⚠️ 详情页要发 5 个请求（runs / preview / compare / feedback / suggestion），
 *    任务不存在时它们会全部 404 —— 页面上会刷出好几个红色错误框。
 *    正确做法：用 catalog 判存在性（零成本），不存在就**一个请求都不发**，
 *    直接显示「任务不存在或已被删除」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { JobDetailPage } from './JobDetailPage'

const CATALOG = {
  sources: [],
  metrics: [],
  jobs: [
    {
      id: 1,
      metric_id: 1,
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

let calls: string[] = []

function renderPage(jobId: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/jobs/${jobId}`]}>
        <Routes>
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
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
      const body = url.includes('/api/platform/catalog')
        ? JSON.stringify(CATALOG)
        : JSON.stringify({ detail: '任务不存在: 999' })
      return new Response(body, {
        status: url.includes('/api/platform/catalog') ? 200 : 404,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('JobDetailPage', () => {
  it('任务不存在时显示友好提示，不是红色错误框', async () => {
    renderPage('999')
    expect(await screen.findByText('任务不存在或已被删除')).toBeTruthy()
  })

  it('任务不存在时一个详情请求都不该发', async () => {
    renderPage('999')
    await screen.findByText('任务不存在或已被删除')
    await waitFor(() => {
      // catalog 要发（用来判存在性），其余详情请求一律不发
      const details = calls.filter((url) => url.includes('/api/platform/jobs/'))
      expect(details).toEqual([])
    })
  })

  it('任务存在时正常发请求', async () => {
    renderPage('1')
    await waitFor(() => {
      const details = calls.filter((url) => url.includes('/api/platform/jobs/'))
      expect(details.length).toBeGreaterThan(0)
    })
    expect(screen.queryByText('任务不存在或已被删除')).toBeNull()
  })
})
