/**
 * 序列总览的交互。
 *
 * 列表项原先是纯文本 —— 用户看到一串序列却点不开，
 * 不知道每条序列长什么样、检测结果如何。
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SeriesOverview } from './SeriesOverview'
import type { SeriesMeta } from '../../api/types'

const SERIES: SeriesMeta[] = [
  {
    series_id: 'periodic-1-100',
    metric_class: 'periodic',
    n: 100,
    n_anomalies: 3,
    start_ts: '2026-01-01T00:00:00',
    end_ts: '2026-01-02T17:35:00',
    source: 'synthetic',
  },
]

describe('SeriesOverview', () => {
  it('序列名可点击 —— 点开看详情', () => {
    const onOpenSeries = vi.fn()
    render(
      <SeriesOverview
        isLoading={false}
        error={null}
        series={SERIES}
        onOpenSeries={onOpenSeries}
      />,
    )
    fireEvent.click(screen.getByText('periodic-1-100'))
    expect(onOpenSeries).toHaveBeenCalledWith('periodic-1-100')
  })

  it('操作列有「详情」按钮', () => {
    const onOpenSeries = vi.fn()
    render(
      <SeriesOverview
        isLoading={false}
        error={null}
        series={SERIES}
        onOpenSeries={onOpenSeries}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /详\s*情/ }))
    expect(onOpenSeries).toHaveBeenCalledWith('periodic-1-100')
  })

  it('显示序列的时间范围', () => {
    render(
      <SeriesOverview
        isLoading={false}
        error={null}
        series={SERIES}
        onOpenSeries={vi.fn()}
      />,
    )
    expect(screen.getByText(/2026-01-01/)).toBeTruthy()
  })
})
