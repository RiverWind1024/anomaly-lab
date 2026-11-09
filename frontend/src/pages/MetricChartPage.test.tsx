/**
 * 指标预览页 —— 选源、选指标、看图。
 *
 * ⚠️ 重点守两件会**静默失效**的事：
 *    1. 「指标能反推数据源」：
 *       从指标列表点「预览」过来时，URL 里只有 `metricId` ——
 *       不反推的话源是空的，指标下拉就是空的，页面显示「还没选指标」。
 *    2. 「选数据源 → 能选指标」：
 *       换源要同时改两个 URL 参数（设 sourceId、删 metricId），
 *       分两次改且都基于**同一个旧快照** → 第二次把第一次覆盖掉 →
 *       URL 变空 → 指标下拉被禁用 → 用户「选不了指标」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { MetricChartPage } from './MetricChartPage'

vi.mock('../features/metrics/MetricChartPanel', () => ({
  MetricChartPanel: () => <div data-testid="chart-panel">最近 30 天</div>,
}))

const CATALOG = {
  sources: [
    { id: 1, name: 'demo-sqlite', kind: 'sqlite', path: '', created_at: '', config: {} },
    { id: 2, name: 'mock-tsdb', kind: 'http', path: '', created_at: '', config: {} },
  ],
  metrics: [
    {
      id: 5,
      source_id: 2,
      name: 'traffic',
      query: 'SELECT ts, value FROM t WHERE $timefilter',
      time_column: 'ts',
      value_column: 'value',
      group_column: null,
      time_format: 'iso_utc',
      freq: '1min',
      source_timezone: 'UTC',
      missing_policy: 'drop',
      created_at: '',
    },
    {
      id: 6,
      source_id: 1,
      name: 'cpu',
      query: 'SELECT ts, value FROM t WHERE $timefilter',
      time_column: 'ts',
      value_column: 'value',
      group_column: null,
      time_format: 'iso_utc',
      freq: '5min',
      source_timezone: 'UTC',
      missing_policy: 'drop',
      created_at: '',
    },
  ],
  jobs: [
    {
      id: 9,
      metric_id: 5,
      name: 'job',
      detector: 'iqr',
      alert_threshold: 2.5,
      critical_threshold: 4,
      window_points: 120,
      interval_seconds: 60,
      enabled: true,
      last_run_at: null,
      next_run_at: null,
      created_at: '',
      alert_rules: [],
    },
  ],
}

/** 记录当前 URL —— 用来断言「换源后参数没被覆盖掉」。 */
function LocationProbe({ onChange }: { onChange: (search: string) => void }) {
  const location = useLocation()
  onChange(location.search)
  return null
}

function renderPage(search = '') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let currentSearch = ''
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/metrics/preview${search}`]}>
        <LocationProbe onChange={(next) => { currentSearch = next }} />
        <Routes>
          <Route path="/metrics/preview" element={<MetricChartPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...utils, search: () => currentSearch }
}

/** 打开第 n 个下拉（antd Select 不是原生 select）。 */
async function openSelect(user: ReturnType<typeof userEvent.setup>, index: number) {
  const combos = screen.getAllByRole('combobox')
  await user.click(combos[index])
}

/** 下拉里的选项（rc-select 用 title 属性放标签）。 */
async function pickOption(user: ReturnType<typeof userEvent.setup>, label: string) {
  const option = await screen.findByTitle(label)
  await user.click(option)
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify(CATALOG), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MetricChartPage', () => {
  it('⚠️ 只有 metricId 时，**反推出数据源**并直接显示图', async () => {
    renderPage('?metricId=5')

    await waitFor(() => {
      expect(screen.getByTestId('chart-panel')).toBeTruthy()
    })
    // 源名应该在数据源下拉里
    expect(screen.getByText(/mock-tsdb/)).toBeTruthy()
  })

  it('预览固定取最近 30 天，不跟任务窗口走', async () => {
    renderPage('?metricId=5')
    await waitFor(() => {
      expect(screen.getByTestId('chart-panel')).toBeTruthy()
    })
    expect(screen.getByTestId('chart-panel').textContent).toContain('最近 30 天')
  })

  it('什么都没选 → 说清楚要选什么', async () => {
    renderPage('')
    await waitFor(() => {
      expect(screen.getByText(/先选数据源，再选指标/)).toBeTruthy()
    })
  })

  it('⚠️ 直接进入页面 → 选数据源后**能选指标**', async () => {
    /* 这里的 bug 是「换源要同时改两个 URL 参数」：
       分两次改、且都基于同一个旧快照 → 第二次把第一次覆盖掉 →
       URL 变空 → sourceId 还是 undefined → 指标下拉被禁用。 */
    const user = userEvent.setup()
    const { search } = renderPage('')

    await waitFor(() => {
      expect(screen.getByText(/先选数据源，再选指标/)).toBeTruthy()
    })

    // 指标下拉此刻是禁用的（还没选源）
    const combosBefore = screen.getAllByRole('combobox')
    expect((combosBefore[1] as HTMLInputElement).disabled).toBe(true)

    await openSelect(user, 0)
    await pickOption(user, 'mock-tsdb · http')

    // ⚠️ URL 里必须有 sourceId
    await waitFor(() => {
      expect(search()).toContain('sourceId=2')
    })

    // ⚠️ 指标下拉必须解禁
    const combosAfter = screen.getAllByRole('combobox')
    expect((combosAfter[1] as HTMLInputElement).disabled).toBe(false)

    // 能选中指标 → 图出来了
    await openSelect(user, 1)
    await pickOption(user, 'traffic')
    await waitFor(() => {
      expect(screen.getByTestId('chart-panel')).toBeTruthy()
    })
    expect(search()).toContain('metricId=5')
  })

  it('⚠️ 换源 → 指标跟着换（旧的 metricId 被清掉）', async () => {
    const user = userEvent.setup()
    const { search } = renderPage('?metricId=5')

    await waitFor(() => {
      expect(screen.getByTestId('chart-panel')).toBeTruthy()
    })

    // 换成另一个源 —— 指标下拉里只剩那个源的指标
    await openSelect(user, 0)
    await pickOption(user, 'demo-sqlite · sqlite')

    await waitFor(() => {
      expect(search()).toContain('sourceId=1')
    })
    // ⚠️ 旧指标属于别的源，必须被清掉
    expect(search()).not.toContain('metricId=5')
    // 换成源 2 → 源 1 的指标 cpu 不在列表里
    await openSelect(user, 1)
    await pickOption(user, 'cpu')
    await waitFor(() => {
      expect(search()).toContain('metricId=6')
    })
  })
})
