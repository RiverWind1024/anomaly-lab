/**
 * 任务配置面板：保存配置。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { JobConfigPanel } from './JobConfigPanel'
import type { CatalogJob } from '../../api/types'

const JOB: CatalogJob = {
  id: 7,
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

describe('JobConfigPanel', () => {
  it('带出任务当前配置', async () => {
    renderWithQuery(
      <JobConfigPanel job={JOB} metrics={[]} detectors={[]} enabled />,
    )
    await waitFor(() => {
      expect((screen.getByLabelText('任务名称') as HTMLInputElement).value).toBe('demo-job')
    })
    expect((screen.getByLabelText(/窗口点数/) as HTMLInputElement).value).toBe('300')
  })

  it('保存走 PATCH，改了什么就发什么', async () => {
    renderWithQuery(
      <JobConfigPanel job={JOB} metrics={[]} detectors={[]} enabled />,
    )
    await waitFor(() => {
      expect((screen.getByLabelText('任务名称') as HTMLInputElement).value).toBe('demo-job')
    })
    fireEvent.change(screen.getByLabelText('任务名称'), { target: { value: '改名了' } })
    fireEvent.click(screen.getByRole('button', { name: /保存配置/ }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch).toBeTruthy()
      expect(patch?.url).toContain('/api/platform/jobs/7')
      const body = JSON.parse(patch?.body ?? '{}')
      expect(body.name).toBe('改名了')
      // 告警规则**不能**被编辑 —— 提交载荷里不该有它
      expect(body.alert_rules).toBeUndefined()
    })
  })

  it('告警规则只读展示', () => {
    renderWithQuery(
      <JobConfigPanel
        job={{ ...JOB, alert_rules: [{ level: 'P1', multiplier: 2.5 }] }}
        metrics={[]}
        detectors={[]}
        enabled
      />,
    )
    expect(screen.getByText(/只读/)).toBeTruthy()
  })
})
