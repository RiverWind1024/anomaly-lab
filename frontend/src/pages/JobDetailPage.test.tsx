/**
 * 任务详情页：分区与请求。
 *
 * 之前这个页面把配置表单、运行记录、预览图、多算法对比、
 * 分类结论、反馈历史全堆在一页 —— 什么都看不清楚。
 * 现在拆成四个独立路由，每个分区只发自己需要的数据。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { JobDetailPage, sectionFromPath } from './JobDetailPage'

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

function renderPage(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          <Route path="/jobs/:jobId/runs" element={<JobDetailPage />} />
          <Route path="/jobs/:jobId/detections" element={<JobDetailPage />} />
          <Route path="/jobs/:jobId/feedback" element={<JobDetailPage />} />
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

describe('sectionFromPath', () => {
  it('按路径后缀判断分区', () => {
    expect(sectionFromPath('/jobs/1')).toBe('config')
    expect(sectionFromPath('/jobs/1/runs')).toBe('runs')
    expect(sectionFromPath('/jobs/1/detections')).toBe('detections')
    expect(sectionFromPath('/jobs/1/feedback')).toBe('feedback')
  })
})

describe('JobDetailPage', () => {
  it('任务不存在时显示友好提示，不是红色错误框', async () => {
    renderPage('/jobs/999')
    expect(await screen.findByText('任务不存在或已被删除')).toBeTruthy()
  })

  it('任务不存在时一个详情请求都不该发', async () => {
    renderPage('/jobs/999')
    await screen.findByText('任务不存在或已被删除')
    await waitFor(() => {
      const details = calls.filter((url) => url.includes('/api/platform/jobs/'))
      expect(details).toEqual([])
    })
  })

  it('默认分区是任务配置 —— 不发检测相关的请求', async () => {
    renderPage('/jobs/1')
    await waitFor(() => {
      expect(calls.some((url) => url.includes('/api/platform/jobs/'))).toBe(true)
    })
    expect(calls.some((url) => url.includes('/compare'))).toBe(false)
    expect(calls.some((url) => url.includes('/preview'))).toBe(false)
  })

  it('检测结果分区才发 preview 与 compare', async () => {
    renderPage('/jobs/1/detections')
    await waitFor(() => {
      expect(calls.some((url) => url.includes('/preview'))).toBe(true)
      expect(calls.some((url) => url.includes('/compare'))).toBe(true)
    })
  })

  it('四个分区都有导航入口', async () => {
    renderPage('/jobs/1')
    await waitFor(() => {
      expect(screen.getByText('任务配置')).toBeTruthy()
    })
    expect(screen.getByText('运行记录')).toBeTruthy()
    expect(screen.getByText('检测结果')).toBeTruthy()
    expect(screen.getByText('人工反馈')).toBeTruthy()
  })
})
