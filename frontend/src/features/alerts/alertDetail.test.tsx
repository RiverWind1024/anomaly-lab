/**
 * 告警中心：筛选与详情。
 *
 * 告警列表原先只有「任务 / 等级」两个下拉，而且每行只有文字 ——
 * 用户看不到「到底什么情况」。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AlertList } from './AlertList'
import { rangeIndices } from './AlertChart'
import type { AlertEvent, AlertListResponse } from '../../api/types'

const event: AlertEvent = {
  job_id: 1,
  job_name: 'demo-job',
  metric_id: 2,
  metric_name: 'demo-metric',
  series_id: 'demo-metric:web-api',
  group: 'web-api',
  level: 'P0',
  level_index: 2,
  start_ts: '2026-10-30T10:00:00',
  end_ts: '2026-10-30T10:05:00',
  n_points: 3,
  max_score: 4.2,
  detector: 'iqr',
  score_type: 'zscore',
  run_id: 7,
}

const DATA: AlertListResponse = {
  events: [event],
  levels: ['P0', 'P1'],
  series: ['demo-metric:web-api', 'demo-metric:db'],
  jobs: [{ id: 1, name: 'demo-job' }],
  skipped: [],
}

let calls: string[] = []

function renderList(filters = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const onFiltersChange = vi.fn()
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AlertList
          isLoading={false}
          error={null}
          data={DATA}
          filters={filters}
          onFiltersChange={onFiltersChange}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...utils, onFiltersChange }
}

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input))
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

describe('rangeIndices', () => {
  it('找出告警区间在时间轴上的下标', () => {
    const stamps = ['10:00', '10:01', '10:02', '10:03']
    expect(rangeIndices(stamps, '10:01', '10:02')).toEqual([1, 2])
  })

  it('区间不在时间轴上时返回 null', () => {
    expect(rangeIndices(['10:00'], '11:00', '11:05')).toBeNull()
  })
})

describe('AlertList 筛选', () => {
  it('有序列筛选下拉', () => {
    renderList()
    expect(screen.getByText('全部序列')).toBeTruthy()
  })

  it('有时间范围选择器', () => {
    renderList()
    expect(screen.getByPlaceholderText('开始时间')).toBeTruthy()
  })

  it('选了筛选条件后有重置按钮', () => {
    renderList({ level: 'P0' })
    expect(screen.getByRole('button', { name: /重\s*置/ })).toBeTruthy()
  })
})

describe('AlertList 详情', () => {
  it('每行都有「详情」按钮', () => {
    renderList()
    expect(screen.getByRole('button', { name: /详\s*情/ })).toBeTruthy()
  })

  it('点「详情」打开抽屉并请求该序列的预览', async () => {
    renderList()
    fireEvent.click(screen.getByRole('button', { name: /详\s*情/ }))
    await waitFor(() => {
      expect(
        calls.some((url) => url.includes('/api/platform/jobs/1/preview')),
      ).toBe(true)
    })
    expect(
      calls.some((url) => url.includes('series_id=demo-metric%3Aweb-api')),
    ).toBe(true)
  })

  it('抽屉里能看到告警区间的信息', async () => {
    renderList()
    fireEvent.click(screen.getByRole('button', { name: /详\s*情/ }))
    await waitFor(() => {
      expect(screen.getByText('2026-10-30 10:00:00')).toBeTruthy()
    })
    // 抽屉里的「峰值分数」是描述项，不是表格单元格
    expect(screen.getAllByText('4.20').length).toBeGreaterThan(0)
  })
})
