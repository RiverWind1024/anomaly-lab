/**
 * 任务配置面板：换算法时提示阈值会跟着换。
 *
 * ⚠️ 背景：统计型的分数是「几个尺度单位」（阈值 2.5），
 *    Chronos 的是 [0,1] 的相对越界程度（阈值 0.5）。
 *    跨族沿用旧阈值 = **告警永远不触发**，而界面显示「一切正常」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { JobConfigPanel } from './JobConfigPanel'
import type { CatalogDetector, CatalogJob, CatalogMetric } from '../../api/types'
import { detectorLabel } from '../../lib/detectorLabels'

const DETECTORS: CatalogDetector[] = [
  { name: 'iqr', default_threshold: 2.5, score_type: 'zscore', label: 'iqr' },
  { name: 'chronos', default_threshold: 0.5, score_type: 'prob', label: 'chronos' },
]

const JOB: CatalogJob = {
  id: 7,
  metric_id: 1,
  name: 'demo-job',
  detector: 'iqr',
  alert_threshold: 2.5,
  critical_threshold: 4,
  window_points: 300,
  interval_seconds: 300,
  enabled: true,
  last_run_at: null,
  next_run_at: null,
  created_at: '2026-10-30T00:00:00+00:00',
  alert_rules: [],
}

const METRICS: CatalogMetric[] = [
  {
    id: 1,
    source_id: 1,
    name: 'demo-metric',
    query: 'SELECT ts, value FROM t WHERE $timefilter',
    time_column: 'ts',
    value_column: 'value',
    group_column: null,
    time_format: 'iso_utc',
    freq: '5min',
    source_timezone: 'UTC',
    missing_policy: 'drop',
    created_at: '2026-10-30T00:00:00+00:00',
  },
]

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <JobConfigPanel job={JOB} metrics={METRICS} detectors={DETECTORS} enabled />
    </QueryClientProvider>,
  )
}

/**
 * 选一个检测算法。
 *
 * ⚠️ antd 的 Select 是 **mousedown** 打开下拉，不是 click。
 * ⚠️ 表单里有两个 Select（指标、算法）—— 按**表单项的标签**定位，
 *    不能拿「第一个 .ant-select」。
 */
function pickDetector(name: string) {
  const item = [...document.querySelectorAll('.ant-form-item')].find((el) =>
    el.textContent?.includes('检测算法'),
  )
  expect(item, '找不到「检测算法」表单项').toBeTruthy()
  const select = item?.querySelector('.ant-select') as HTMLElement
  fireEvent.mouseDown(select.querySelector('.ant-select-selector') as HTMLElement)
  // ⚠️ 下拉里显示的是**中文标签 + 惯用阈值**（统一的 detectorLabel 映射），
  //    底层值仍是原始算法名
  const option = [...document.querySelectorAll('.ant-select-item-option')].find(
    (el) => el.textContent?.startsWith(detectorLabel(name)),
  )
  expect(option, `找不到选项 ${name}`).toBeTruthy()
  fireEvent.click(option as HTMLElement)
}

describe('JobConfigPanel', () => {
  it('换算法时提示阈值会自动换', async () => {
    renderPanel()
    pickDetector('chronos')

    await waitFor(() => {
      expect(screen.getByText(/告警阈值会自动换成 0.5/)).toBeTruthy()
    })
  })

  it('同量纲的算法不提示', () => {
    renderPanel()
    pickDetector('iqr')

    expect(screen.queryByText(/告警阈值会自动换成/)).toBeNull()
  })

  it('⚠️ 告警规则**可以改** —— 改完保存时带上新的规则表', async () => {
    /* 之前规则是只读的（后端没有编辑端点）——
       2.5 / 3.75 这两个恰恰是最该能调的数。 */
    const user = userEvent.setup()
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ id: 7 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    renderPanel()

    const input = screen.getByDisplayValue('2.5')
    await user.clear(input)
    await user.type(input, '5')
    await user.click(screen.getByRole('button', { name: /保\s*存\s*配\s*置/ }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => c[1]?.method === 'PATCH')
      expect(call, '没有发出 PATCH').toBeTruthy()
      const body = JSON.parse((call?.[1] as RequestInit).body as string)
      // ⚠️ P1 改成 5 后比 P0 的 4 更大 —— 按倍数升序，P0 排到了前面
      expect(body.alert_rules).toEqual([
        { multiplier: 4, level: 'P0' },
        { multiplier: 5, level: 'P1' },
      ])
    })
    vi.unstubAllGlobals()
  })
})
