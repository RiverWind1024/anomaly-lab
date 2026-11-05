/**
 * 「按实际范围重跑」—— 区间怎么算、点了之后交回什么。
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RangeSuggestion, actualRangeOf } from './RangeSuggestion'
import type { LabSeries } from '../../api/types'

function _series(overrides: Partial<LabSeries> = {}): LabSeries {
  return {
    series_id: 'm:a',
    group: 'a',
    n: 100,
    data_start: '2026-01-01T00:00:00+00:00',
    data_end: '2026-01-05T04:00:00+00:00',
    windows: [],
    shape: null,
    ...overrides,
  }
}

describe('actualRangeOf', () => {
  it('没有可用区间时返回 null', () => {
    expect(actualRangeOf([])).toBeNull()
    expect(actualRangeOf([_series({ data_start: null, data_end: null })])).toBeNull()
  })

  it('单条序列用它的起止', () => {
    const range = actualRangeOf([_series()])
    expect(range?.start.toISOString()).toBe('2026-01-01T00:00:00.000Z')
    expect(range?.end.toISOString()).toBe('2026-01-05T04:00:00.000Z')
  })

  it('多条序列取并集 —— 不能漏掉一部分序列', () => {
    const range = actualRangeOf([
      _series({ series_id: 'a', data_start: '2026-01-02T00:00:00+00:00', data_end: '2026-01-03T00:00:00+00:00' }),
      _series({ series_id: 'b', data_start: '2026-01-01T00:00:00+00:00', data_end: '2026-01-09T00:00:00+00:00' }),
    ])
    expect(range?.start.toISOString()).toBe('2026-01-01T00:00:00.000Z')
    expect(range?.end.toISOString()).toBe('2026-01-09T00:00:00.000Z')
  })
})

describe('RangeSuggestion', () => {
  it('没有区间时不渲染', () => {
    const { container } = render(
      <RangeSuggestion series={[_series({ data_start: null, data_end: null })]} onApply={() => {}} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('点「按实际范围重跑」把数据实际区间交回去', async () => {
    const user = userEvent.setup()
    const onApply = vi.fn()
    render(<RangeSuggestion series={[_series()]} onApply={onApply} />)

    expect(screen.getByText(/数据实际覆盖/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '按实际范围重跑' }))

    expect(onApply).toHaveBeenCalledTimes(1)
    const [start, end] = onApply.mock.calls[0][0]
    expect(start.toISOString()).toBe('2026-01-01T00:00:00.000Z')
    expect(end.toISOString()).toBe('2026-01-05T04:00:00.000Z')
  })
})
