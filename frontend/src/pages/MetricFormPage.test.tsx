/**
 * 指标配置页（新增 / 编辑共用）。
 *
 * ⚠️ 这些行为原先由弹窗（`MetricForm`）保证 ——
 *    换成独立页面后，一样要守住。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { MetricFormPage } from './MetricFormPage'
import type { CatalogMetric, CatalogSource } from '../api/types'

const SOURCE: CatalogSource = {
  id: 1,
  name: 'demo-sqlite',
  kind: 'sqlite',
  path: 'platform/source.db',
  created_at: '2026-10-30T00:00:00+00:00',
}

const METRIC: CatalogMetric = {
  id: 7,
  source_id: 1,
  name: 'cpu',
  query: 'SELECT ts, value FROM metrics WHERE $timefilter',
  time_column: 'ts',
  value_column: 'value',
  group_column: 'host',
  time_format: 'iso_utc',
  freq: '5min',
  source_timezone: 'UTC',
  missing_policy: 'drop',
  created_at: '2026-10-30T00:00:00+00:00',
}

const CATALOG = {
  sources: [SOURCE],
  metrics: [METRIC],
  jobs: [],
  detectors: [],
}

let calls: Array<{ url: string; method: string; body: string }> = []

function renderPage(path: string, node: ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/metrics/new" element={node} />
          <Route path="/metrics/:metricId/edit" element={node} />
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
      calls.push({
        url: String(input),
        method: init?.method ?? 'GET',
        body: String(init?.body ?? ''),
      })
      if (String(input).includes('/api/platform/catalog')) {
        return new Response(JSON.stringify(CATALOG), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ id: 7 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('指标配置页', () => {
  it('编辑态带出原值', async () => {
    renderPage('/metrics/7/edit', <MetricFormPage />)
    await waitFor(() => {
      expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('cpu')
    })
    expect((screen.getByLabelText(/分组列/) as HTMLInputElement).value).toBe('host')
    expect((screen.getByLabelText(/查询语句/) as HTMLTextAreaElement).value).toContain(
      '$timefilter',
    )
  })

  it('保存走 PATCH，且带上改后的值', async () => {
    renderPage('/metrics/7/edit', <MetricFormPage />)
    await waitFor(() => {
      expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('cpu')
    })
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: 'cpu2' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch).toBeTruthy()
      expect(patch?.url).toContain('/api/platform/metrics/7')
      expect(JSON.parse(patch?.body ?? '{}').name).toBe('cpu2')
    })
    // ⚠️ 页内预览会发一个 POST 到 `/sources/{id}/query` ——
    //    那是**预览取数**，不是保存。要断言的是「没往 metrics 发 POST」。
    expect(
      calls.some((c) => c.method === 'POST' && c.url.includes('/api/platform/metrics')),
    ).toBe(false)
  })

  it('新增态走 POST', async () => {
    renderPage('/metrics/new?source_id=1', <MetricFormPage />)
    await waitFor(() => expect(screen.getByLabelText('名称')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '新指标' } })
    fireEvent.click(screen.getByRole('button', { name: /新\s*增/ }))

    await waitFor(() => {
      // ⚠️ 页内预览也会 POST —— 要按 URL 挑出保存那个
      const post = calls.find(
        (c) => c.method === 'POST' && c.url.includes('/api/platform/metrics'),
      )
      expect(post).toBeTruthy()
      expect(JSON.parse(post?.body ?? '{}').name).toBe('新指标')
    })
  })

  it('指标不存在时给出提示', async () => {
    renderPage('/metrics/999/edit', <MetricFormPage />)
    expect(await screen.findByText('指标不存在或已被删除')).toBeTruthy()
  })

  it('⚠️ 预览是**页内**的 —— 不再跳去另一个页面', async () => {
    /* 原来这个按钮跳到 `/metric-preview`（新标签页）——
       跳来跳去看不到「改了什么」。现在直接画在页面底部。 */
    renderPage('/metrics/7/edit', <MetricFormPage />)
    await waitFor(() => {
      expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('cpu')
    })
    expect(screen.queryByRole('link', { name: '预览数据' })).toBeNull()
    expect(screen.getByRole('heading', { name: '预览数据' })).toBeTruthy()
  })

  it('⚠️ 提示窗口在**告警任务**里设 —— 指标本身没有这个字段', async () => {
    renderPage('/metrics/7/edit', <MetricFormPage />)
    await waitFor(() => {
      expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('cpu')
    })
    expect(screen.getByText(/指标本身没有「取多少数据」的设置/)).toBeTruthy()
  })
})
