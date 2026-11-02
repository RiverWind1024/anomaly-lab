/**
 * 概览页：展示整个系统的运行情况。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DashboardPage, fmtBytes, fmtDuration, sinceLabel } from './DashboardPage'
import type { Overview } from '../api/types'

const OVERVIEW: Overview = {
  counts: { sources: 2, metrics: 5, jobs: 3, enabled_jobs: 2 },
  runs: { total: 42, success: 40, failed: 2, running: 0 },
  alerts: {
    total: 17,
    by_level: [
      { level: 'P0', count: 4 },
      { level: 'P1', count: 13 },
    ],
    by_job: [{ job_id: 1, job_name: 'demo-job', count: 17 }],
    top_series: [{ series_id: 'demo-metric:web-api', count: 12 }],
    skipped: 1,
  },
  feedback: {
    total: 5,
    by_kind: [{ kind: 'missed', count: 3 }],
  },
  jobs: [
    {
      id: 1,
      name: 'demo-job',
      enabled: true,
      detector: 'iqr',
      metric_id: 1,
      last_run: {
        id: 50,
        status: 'success',
        started_at: '2026-10-30T10:00:00+00:00',
        finished_at: '2026-10-30T10:00:30+00:00',
        n_series: 2,
        n_alerts: 24,
        error: null,
      },
    },
  ],
}

const SUMMARY = {
  generated_at: '2026-10-30T00:00:00+00:00',
  title: '回测',
  summary: {
    overall: {
      n_series: 120,
      n_truth: 300,
      n_pred: 200,
      precision: 0.529,
      recall: 0.295,
      f1: 0.31,
      range_f1: 0.205,
    },
  },
  rows: [],
}

const STORAGE = {
  policy: { retention_days: 180 },
  runs: { kept: 42, n_dirs: 42, bytes: 1048576 },
  database: { path: 'data/platform.db', bytes: 65536 },
  feedback: { total: 5 },
  last_pruned_at: '2026-10-30T10:00:00+00:00',
  last_pruned: { deleted_runs: 703, freed_bytes: 9989731 },
}

let calls: string[] = []

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DashboardPage />
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
      const body = url.includes('/api/platform/overview')
        ? JSON.stringify(OVERVIEW)
        : url.includes('/api/platform/storage')
          ? JSON.stringify(STORAGE)
          : url.includes('/api/summary')
            ? JSON.stringify(SUMMARY)
            : '{}'
      return new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fmtDuration', () => {
  it('不到一分钟显示秒', () => {
    expect(
      fmtDuration('2026-10-30T10:00:00+00:00', '2026-10-30T10:00:30+00:00'),
    ).toBe('30 秒')
  })

  it('超过一分钟显示分秒', () => {
    expect(
      fmtDuration('2026-10-30T10:00:00+00:00', '2026-10-30T10:02:05+00:00'),
    ).toBe('2 分 5 秒')
  })

  it('没跑完显示占位', () => {
    expect(fmtDuration('2026-10-30T10:00:00+00:00', null)).toBe('—')
  })
})

describe('sinceLabel', () => {
  it('没跑过', () => {
    expect(sinceLabel(null)).toBe('从未运行')
  })
})

describe('fmtBytes', () => {
  it('字节', () => {
    expect(fmtBytes(512)).toBe('512 B')
  })

  it('兆字节', () => {
    expect(fmtBytes(1048576)).toBe('1.0 MB')
  })

  it('零与非法值', () => {
    expect(fmtBytes(0)).toBe('0 B')
    expect(fmtBytes(NaN)).toBe('0 B')
  })
})

describe('DashboardPage', () => {
  it('展示关键计数', async () => {
    renderPage()
    expect(await screen.findByText('数据源')).toBeTruthy()
    expect(screen.getByText('指标')).toBeTruthy()
    expect(screen.getByText('检测任务')).toBeTruthy()
    expect(screen.getByText('当前告警')).toBeTruthy()
    // ⚠️ 不是「累计运行」—— 保留策略会清掉超窗的，这个数是保留窗口内的
    expect(screen.getByText('保留期运行')).toBeTruthy()
    expect(screen.queryByText('累计运行')).toBeNull()
    // 「人工反馈」既是统计卡标题也是卡片标题 —— 会出现两次
    expect(screen.getAllByText('人工反馈').length).toBeGreaterThan(0)
  })

  it('⚠️ 展示数据保留：占用、策略、上次清理', async () => {
    renderPage()
    expect(await screen.findByText('数据保留')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('保留策略')).toBeTruthy())
    expect(screen.getByText(/最近 180 天/)).toBeTruthy()
    expect(screen.getByText('1.0 MB')).toBeTruthy()
  })

  it('「立即清理」会调清理端点', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('立即清理')).toBeTruthy())
    const button = screen.getByRole('button', { name: /立\s*即\s*清\s*理/ })
    button.click()
    await waitFor(() =>
      expect(calls.some((url) => url.includes('/api/platform/prune'))).toBe(true),
    )
  })

  it('展示告警分布与最多的序列', async () => {
    renderPage()
    expect(await screen.findByText('告警分布')).toBeTruthy()
    expect(screen.getByText('demo-metric:web-api')).toBeTruthy()
    expect(screen.getByText('P0')).toBeTruthy()
  })

  it('展示任务运行状况', async () => {
    renderPage()
    expect(await screen.findByText('任务运行状况')).toBeTruthy()
    const link = screen.getByRole('link', { name: 'demo-job' })
    expect(link.getAttribute('href')).toBe('/jobs/1')
    expect(screen.getByText('30 秒')).toBeTruthy()
  })

  it('展示回测总体', async () => {
    renderPage()
    expect(await screen.findByText('回测总体')).toBeTruthy()
    expect(screen.getByText('0.310')).toBeTruthy()
  })

  it('只发两个请求（概览 + 报告），不逐个任务查', async () => {
    renderPage()
    await screen.findByText('数据源')
    expect(calls.filter((url) => url.includes('/api/platform/jobs/'))).toEqual([])
    expect(calls.some((url) => url.includes('/api/platform/overview'))).toBe(true)
  })
})
