/**
 * 试跑面板：真实执行但不落库。
 *
 * ⚠️ 面板本身**不该**产生任何持久化副作用 ——
 *    前端只是调一个端点，不该顺手失效掉运行记录与告警的缓存。
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { TestRunPanel } from './TestRunPanel'

/**
 * 图表换成占位 —— ECharts 要 canvas，jsdom 没实现。
 *
 * ⚠️ 这不是「测不到就不测」—— 图表本身有独立的测试
 *    （`PreviewChart.test.tsx`）；这里要测的是**试跑的接线与结果呈现**。
 */
vi.mock('./PreviewChart', () => ({
  PreviewChart: () => <div data-testid="preview-chart" />,
}))

const TEST_RUN = {
  job_id: 7,
  detector: 'iqr',
  requested_detector: 'auto',
  metric_class: 'periodic',
  detector_rationale: '形态像周期型',
  detector_fallback: false,
  score_type: 'zscore',
  n_series: 1,
  n_alerts: 2,
  n_p0: 1,
  n_insufficient: 0,
  alert_threshold: 2.5,
  critical_threshold: 4,
  alert_rules: [
    { multiplier: 2.5, level: 'P1' },
    { multiplier: 4, level: 'P0' },
  ],
  levels: ['正常', 'P1', 'P0'],
  series: [
    {
      series_id: 'demo-metric:web-api',
      group: 'web-api',
      n: 12,
      n_valid: 12,
      n_missing: 0,
      n_alerts: 2,
      n_p0: 1,
      sufficient: true,
      detector: 'iqr',
      metric_class: 'periodic',
      fallback: false,
      file: null,
    },
  ],
  results: [
    {
      series_id: 'demo-metric:web-api',
      group: 'web-api',
      sufficient: true,
      insufficient_reason: '',
      n: 12,
      n_valid: 12,
      n_missing: 0,
      n_alerts: 2,
      n_p0: 1,
      timestamps: ['2026-11-03T00:00:00', '2026-11-03T00:05:00'],
      values: [10, 80],
      scores: [0.1, 9.5],
      baseline: [10, 10],
      lower: [7, 7],
      upper: [13, 13],
      severity: [0, 2],
    },
  ],
  alerts: [
    {
      series_id: 'demo-metric:web-api',
      group: 'web-api',
      index: 1,
      timestamp: '2026-11-03T00:05:00',
      value: 80,
      score: 9.5,
      severity: 2,
      level: 'P0',
    },
  ],
}

let calls: string[] = []

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TestRunPanel jobId={7} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input))
      return new Response(JSON.stringify(TEST_RUN), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TestRunPanel', () => {
  it('点「试跑一次」才发请求 —— 打开页面不该自动跑', () => {
    renderPanel()
    expect(calls).toHaveLength(0)
    expect(screen.getByText('试跑一次')).toBeTruthy()
  })

  it('试跑调用 test-run 端点', async () => {
    const user = userEvent.setup()
    renderPanel()
    await user.click(screen.getByText('试跑一次'))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toContain('/api/platform/jobs/7/test-run')
  })

  it('结果里给出告警点与统计', async () => {
    const user = userEvent.setup()
    renderPanel()
    await user.click(screen.getByText('试跑一次'))
    await waitFor(() => expect(screen.getByText(/2 个告警点/)).toBeTruthy())
    // ⚠️ 「P0」出现多处（统计行 + 告警级别列 + 规则表）—— 用 getAllByText
    expect(screen.getAllByText('P0').length).toBeGreaterThan(0)
    // 告警点表里的分数与值
    expect(screen.getByText('9.500')).toBeTruthy()
    expect(screen.getByText('80.000')).toBeTruthy()
  })

  it('说明试跑不落库 —— 免得用户以为它进了告警记录', async () => {
    const user = userEvent.setup()
    renderPanel()
    expect(screen.getByText(/不会进告警记录/)).toBeTruthy()
    await user.click(screen.getByText('试跑一次'))
    await waitFor(() => expect(screen.getByText(/再试一次/)).toBeTruthy())
  })

  it('无法判定时不说「数值都在正常带里」', async () => {
    // 常数序列：没有可用尺度，零告警不等于「一切正常」
    const undetermined = {
      ...TEST_RUN,
      n_alerts: 0,
      n_p0: 0,
      alerts: [],
      series: [
        {
          ...TEST_RUN.series[0],
          n_alerts: 0,
          n_p0: 0,
          scale_source: 'none',
          status: 'undetermined',
          scale_fallback: false,
        },
      ],
      results: [
        {
          ...TEST_RUN.results[0],
          n_alerts: 0,
          n_p0: 0,
          scores: [0, 0],
          severity: [0, 0],
        },
      ],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(undetermined), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const user = userEvent.setup()
    renderPanel()
    await user.click(screen.getByText('试跑一次'))
    await waitFor(() => expect(screen.getAllByText('无法判定').length).toBeGreaterThan(0))
    expect(screen.queryByText(/正常带里/)).toBeNull()
  })

  it('配了「只报偏低」但算法没有基线时给出警告', async () => {
    // 无基线算法：direction_applied=false，本次一条都不会报 ——
    // 不能静默显示「0 个告警点」让人以为一切正常。
    const unsupported = {
      ...TEST_RUN,
      alert_direction: 'below',
      n_alerts: 0,
      n_p0: 0,
      alerts: [],
      series: [
        {
          ...TEST_RUN.series[0],
          n_alerts: 0,
          n_p0: 0,
          alert_direction: 'below',
          direction_applied: false,
        },
      ],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(unsupported), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const user = userEvent.setup()
    renderPanel()
    await user.click(screen.getByText('试跑一次'))

    await waitFor(() =>
      expect(screen.getByText(/无法判断「偏低」/)).toBeTruthy(),
    )
  })

  it('试跑失败时把原因显示出来', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: '取数失败：连接被拒绝' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const user = userEvent.setup()
    renderPanel()
    await user.click(screen.getByText('试跑一次'))
    await waitFor(() => expect(screen.getByText('试跑失败')).toBeTruthy())
  })
})
