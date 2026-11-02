/**
 * 概览页：展示整个系统的运行情况。
 *
 * 这一屏回答一个问题：**现在哪里有异常？**
 * 所以最大的那块是异常分数轨迹，数字在下面的 KPI 条里。
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
    by_metric_class: {
      sparse_event: {
        n_series: 40,
        n_truth: 1426,
        n_pred: 0,
        precision: 0,
        recall: 0,
        f1: 0,
        range_f1: 0,
        elapsed_ms: 10,
      },
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

/** 轨迹用的一次运行的检测结果。 */
const PREVIEW = {
  run_id: 50,
  job_id: 1,
  detector: 'iqr',
  requested_detector: 'iqr',
  metric_class: 'periodic',
  detector_rationale: '',
  detector_fallback: false,
  score_type: 'zscore',
  series_id: 'demo-metric:web-api',
  group: 'web-api',
  n: 4,
  n_valid: 4,
  n_missing: 0,
  n_alerts: 2,
  n_p0: 1,
  sufficient: true,
  insufficient_reason: '',
  sampled: false,
  original_n: 4,
  timestamps: [
    '2026-10-30T09:30:00',
    '2026-10-30T09:35:00',
    '2026-10-30T09:40:00',
    '2026-10-30T09:45:00',
  ],
  values: [1, 2, 3, 4],
  scores: [0.2, 1.1, 3.4, 0.5],
  baseline: null,
  lower: null,
  upper: null,
  severity: [0, 1, 2, 0],
  alert_threshold: 2.5,
  critical_threshold: 4,
  alert_rules: [],
  levels: ['normal', 'P1', 'P0'],
  series: [
    {
      series_id: 'demo-metric:web-api',
      group: 'web-api',
      n: 4,
      n_valid: 4,
      n_missing: 0,
      n_alerts: 2,
      n_p0: 1,
      sufficient: true,
      detector: 'iqr',
      metric_class: 'periodic',
      fallback: false,
      file: 'x',
    },
    {
      series_id: 'demo-metric:web-worker',
      group: 'web-worker',
      n: 4,
      n_valid: 4,
      n_missing: 0,
      n_alerts: 1,
      n_p0: 0,
      sufficient: true,
      detector: 'iqr',
      metric_class: 'periodic',
      fallback: false,
      file: 'x',
    },
  ],
}

const ALERTS = {
  events: [
    {
      job_id: 1,
      job_name: 'demo-job',
      metric_id: 1,
      metric_name: 'demo-metric',
      series_id: 'demo-metric:web-api',
      group: 'web-api',
      level: 'P0',
      level_index: 2,
      start_ts: '2026-10-30T09:40:00+00:00',
      end_ts: '2026-10-30T09:45:00+00:00',
      n_points: 3,
      max_score: 3.4,
      detector: 'iqr',
      score_type: 'zscore',
      run_id: 50,
    },
  ],
  jobs: [],
  levels: [],
  series: [],
  skipped: [],
}

const CATALOG = {
  sources: [],
  metrics: [],
  detectors: [],
  jobs: [
    {
      id: 1,
      metric_id: 1,
      name: 'demo-job',
      detector: 'iqr',
      alert_threshold: 2.5,
      critical_threshold: 4,
      window_points: 100,
      interval_seconds: 300,
      enabled: true,
      last_run_at: '2026-10-30T10:00:00+00:00',
      next_run_at: '2026-10-30T10:05:00+00:00',
      created_at: '2026-10-01T00:00:00+00:00',
      alert_rules: [],
    },
  ],
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
          : url.includes('/api/platform/catalog')
            ? JSON.stringify(CATALOG)
            : url.includes('/api/platform/alerts')
              ? JSON.stringify(ALERTS)
              : url.includes('/preview')
                ? JSON.stringify(PREVIEW)
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
    expect(await screen.findByText('检测任务')).toBeTruthy()
    expect(screen.getByText('数据源 / 指标')).toBeTruthy()
    expect(screen.getByText('人工反馈')).toBeTruthy()
    expect(screen.getByText('回测序列')).toBeTruthy()
    // ⚠️ 不是「累计运行」—— 保留策略会清掉超窗的，这个数是保留窗口内的
    expect(screen.getByText('保留期运行')).toBeTruthy()
    expect(screen.queryByText('累计运行')).toBeNull()
  })

  it('KPI 条里给出告警总数与 P0 数', async () => {
    renderPage()
    // 总数与 P0 数 —— 页面顶部不再有说明行，这两个数在 KPI 条里
    await waitFor(() => {
      const strip = document.querySelector('.kpis')
      expect(strip?.textContent ?? '').toContain('告警')
    })
    const strip = document.querySelector('.kpis')?.textContent ?? ''
    expect(strip).toContain('17')
    expect(strip).toContain('4 条 P0')
  })

  it('⚠️ 展示数据保留：占用、策略、上次清理', async () => {  // taste-skill-ignore
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

  it('画异常分数轨迹，并给出可切换的序列', async () => {
    renderPage()
    const chart = await screen.findByRole('img', { name: /异常分数轨迹/ })
    expect(chart.getAttribute('aria-label')).toContain('demo-metric:web-api')
    // 序列切换：两条序列，告警多的那条排在前面
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /web-api/ })).toBeTruthy(),
    )
    expect(screen.getByRole('tab', { name: /web-worker/ })).toBeTruthy()
  })

  it('告警事件列出当前序列的事件', async () => {
    renderPage()
    expect(await screen.findByText('告警事件')).toBeTruthy()
    await waitFor(() => expect(screen.getAllByText('P0').length).toBeGreaterThan(0))
    // 峰值在图上与事件行各出现一次
    expect(screen.getAllByText('3.40σ').length).toBeGreaterThan(0)
  })

  it('展示任务运行状况', async () => {
    renderPage()
    expect(await screen.findByText('任务运行状况')).toBeTruthy()
    const link = screen.getByRole('link', { name: 'demo-job' })
    expect(link.getAttribute('href')).toBe('/jobs/1')
    // 耗时在任务行与「最近一次运行」里各出现一次
    expect(screen.getAllByText('30 秒').length).toBeGreaterThan(0)
  })

  it('展示回测总体，并指出最弱的形态', async () => {
    renderPage()
    expect(await screen.findByText('回测总体')).toBeTruthy()
    expect(screen.getByText('0.310')).toBeTruthy()
    expect(screen.getByText(/sparse_event/)).toBeTruthy()
  })

  it('只查一次任务详情，不逐个任务查', async () => {
    renderPage()
    await screen.findByText('数据源 / 指标')
    // ⚠️ 轨迹只查**一个**任务的最近一次运行 —— 不能每个任务都查一遍
    const previewCalls = calls.filter((url) => url.includes('/preview'))
    expect(previewCalls.length).toBeLessThanOrEqual(1)
    expect(calls.some((url) => url.includes('/api/platform/jobs/') && url.includes('/runs'))).toBe(
      false,
    )
    expect(calls.some((url) => url.includes('/api/platform/overview'))).toBe(true)
  })
})
