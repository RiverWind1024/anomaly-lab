/**
 * 指标预览面板 —— 用指标的取数配置跑一次，画图 + 明细。
 *
 * ⚠️ 重点守两件事：
 *    1. 时间范围由**后端**按 `freq` + `window_points` 算
 *       （与指标运行时同一段代码）—— 前端自己算就会漂移；
 *    2. SQL 非法时**显示错误**，不静默空着。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { MetricChartPanel } from './MetricChartPanel'

// ⚠️ ECharts 在 jsdom 里没有宽高 —— 有数据时会抛错。
//    图本身由 `BrowseChart.test.tsx` 测（纯函数），这里只测取数与表格。
vi.mock('../sources/BrowseChart', () => ({
  BrowseChart: () => <div data-testid="browse-chart" />,
  extractBrowseSeries: () => [],
}))

const RESULT = {
  columns: [
    { name: 'ts', type: 'TIMESTAMP' },
    { name: 'value', type: 'REAL' },
  ],
  rows: [['2026-10-30T09:00:00+00:00', 3.5]],
  time_values: [1793670360000],
  total: 1,
  truncated: false,
  elapsed_ms: 7,
}

const CONFIG = {
  query: 'SELECT ts, value FROM t WHERE $timefilter',
  time_column: 'ts',
  value_column: 'value',
  group_column: null,
  time_format: 'iso_utc',
  source_timezone: 'UTC',
}

function renderPanel(props: Partial<React.ComponentProps<typeof MetricChartPanel>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MetricChartPanel
        sourceId={3}
        config={CONFIG}
        windowPoints={60}
        freq="1min"
        {...props}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify(RESULT), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MetricChartPanel', () => {
  it('⚠️ 请求带上 freq + window_points —— 时间范围由**后端**算', async () => {
    renderPanel({ windowPoints: 120, freq: '5min' })

    await waitFor(() => {
      expect((globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(0)
    })
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    const body = JSON.parse((call[1] as RequestInit).body as string)
    expect(body.freq).toBe('5min')
    expect(body.window_points).toBe(120)
    // ⚠️ 不传 start/end —— 让后端按窗口算
    expect(body.start).toBeUndefined()
    expect(body.end).toBeUndefined()
  })

  it('SQL 非法 → 显示错误，不静默空着', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'SQL 执行失败: no such table: t' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    renderPanel()

    await waitFor(() => {
      expect(screen.getByText(/no such table/)).toBeTruthy()
    })
  })

  it('⚠️ SQL 里没有 $timefilter → 提醒时间窗口不生效', async () => {
    renderPanel({
      config: { ...CONFIG, query: 'SELECT ts, value FROM t' },
    })

    await waitFor(() => {
      expect(screen.getByText(/时间窗口不生效/)).toBeTruthy()
    })
  })

  it('跑出结果 → 显示行数与窗口说明', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/1 行/)).toBeTruthy()
    })
  })
})
