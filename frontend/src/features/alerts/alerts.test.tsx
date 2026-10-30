import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { AlertEvent, AlertListResponse } from '../../api/types'
import { AlertList } from './AlertList'

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

function renderList(data: AlertListResponse) {
  // AlertList 里有 react-router 的 Link —— 必须包 Router
  return render(
    <MemoryRouter>
      <AlertList
        isLoading={false}
        error={null}
        data={data}
        filters={{ jobId: undefined, level: undefined }}
        onFiltersChange={() => {}}
      />
    </MemoryRouter>,
  )
}

describe('AlertList', () => {
  it('渲染事件的等级与时间区间', () => {
    renderList({
      events: [event],
      levels: ['P0'],
      jobs: [{ id: 1, name: 'demo-job' }],
      skipped: [],
    })
    expect(screen.getByText('P0')).toBeTruthy()
    expect(screen.getByText(/2026-10-30 10:00/)).toBeTruthy()
  })

  it('任务名渲染成链接指向任务详情', () => {
    renderList({
      events: [event],
      levels: ['P0'],
      jobs: [{ id: 1, name: 'demo-job' }],
      skipped: [],
    })
    const link = screen.getByRole('link', { name: 'demo-job' })
    expect(link.getAttribute('href')).toBe('/jobs/1')
  })

  it('渲染点数与峰值分数', () => {
    renderList({
      events: [event],
      levels: ['P0'],
      jobs: [{ id: 1, name: 'demo-job' }],
      skipped: [],
    })
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByText('4.20')).toBeTruthy()
  })

  it('有任务但没有事件时显示「当前没有告警」', () => {
    renderList({
      events: [],
      levels: [],
      jobs: [{ id: 1, name: 'demo-job' }],
      skipped: [],
    })
    expect(screen.getByText('当前没有告警')).toBeTruthy()
  })

  it('一个任务都没有时显示「还没有检测任务」', () => {
    renderList({ events: [], levels: [], jobs: [], skipped: [] })
    expect(screen.getByText('还没有检测任务')).toBeTruthy()
  })

  it('跳过的任务如实展示原因', () => {
    renderList({
      events: [],
      levels: [],
      jobs: [{ id: 1, name: 'demo-job' }],
      skipped: [{ job_id: 1, name: 'demo-job', reason: '还没有运行记录' }],
    })
    expect(screen.getByText(/还没有运行记录/)).toBeTruthy()
  })
})
