import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { MetricForm } from './MetricForm'
import { MetricList } from './MetricList'
import type { CatalogMetric, CatalogSource } from '../../api/types'

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

let calls: Array<{ url: string; method: string; body: string }> = []

function renderWithQuery(node: ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>)
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
      return new Response('{}', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('指标编辑', () => {
  it('列表有「编辑」按钮', () => {
    renderWithQuery(
      <MetricList
        isLoading={false}
        error={null}
        metrics={[METRIC]}
        sources={[SOURCE]}
        catalog={undefined}
        onDelete={vi.fn()}
        deletingId={null}
        onEdit={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /编\s*辑/ })).toBeTruthy()
  })

  it('编辑弹窗带出原值', async () => {
    renderWithQuery(
      <MetricForm open editing={METRIC} sources={[SOURCE]} onCancel={vi.fn()} onSuccess={vi.fn()} />,
    )
    await waitFor(() => {
      expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('cpu')
    })
    expect((screen.getByLabelText(/分组列/) as HTMLInputElement).value).toBe('host')
  })

  it('保存走 PATCH，且带上改后的值', async () => {
    renderWithQuery(
      <MetricForm open editing={METRIC} sources={[SOURCE]} onCancel={vi.fn()} onSuccess={vi.fn()} />,
    )
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
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })
})
