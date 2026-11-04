import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { EvaluationRow } from '../../api/types'
import { FilterBar } from './FilterBar'
import { detectorLabel } from '../../lib/detectorLabels'

const rows: EvaluationRow[] = [
  {
    series_id: 'a',
    metric_class: 'periodic',
    detector: 'iqr',
    score_type: 'zscore',
    threshold: 2.5,
    precision: 1,
    recall: 0.5,
    f1: 0.5,
    range_f1: 0.5,
    n_truth: 1,
    n_pred: 1,
    elapsed_ms: 0.1,
    source: 'synthetic',
  },
  {
    ...({
      series_id: 'b',
      metric_class: 'stationary',
      detector: 'mad',
      score_type: 'zscore',
      threshold: 2.5,
      precision: 1,
      recall: 0.5,
      f1: 0.5,
      range_f1: 0.5,
      n_truth: 1,
      n_pred: 1,
      elapsed_ms: 0.1,
      source: 'synthetic',
    } as EvaluationRow),
  },
]

function pickerValues(): string[] {
  return [...document.querySelectorAll('.ant-picker input')].map(
    (el) => (el as HTMLInputElement).value,
  )
}

describe('FilterBar', () => {
  it('五个筛选维度都有控件', () => {
    render(<FilterBar rows={rows} filters={{}} onChange={() => {}} />)
    expect(document.querySelectorAll('.ant-picker input').length).toBe(2)
    const placeholders = [...document.querySelectorAll('.ant-select-selection-placeholder')].map(
      (el) => el.textContent,
    )
    expect(placeholders).toEqual(['全部算法', '全部形态', '全部来源'])
  })

  it('⚠️ 时间范围是**受控**的 —— filters 清空后输入框也跟着清空', () => {  // taste-skill-ignore
    const { rerender } = render(
      <FilterBar
        rows={rows}
        filters={{ since: '2026-01-01T00:00:00', until: '2026-01-05T00:00:00' }}
        onChange={() => {}}
      />,
    )
    expect(pickerValues()).toEqual(['2026-01-01 00:00:00', '2026-01-05 00:00:00'])

    // 「重置」把 filters 清空 —— 输入框必须跟着清空，
    // 否则计数复位了但界面还显示旧范围，看着像没生效。
    rerender(<FilterBar rows={rows} filters={{}} onChange={() => {}} />)
    expect(pickerValues()).toEqual(['', ''])
  })

  it('选算法 → onChange 带上合并后的筛选条件', async () => {
    const onChange = vi.fn()
    render(<FilterBar rows={rows} filters={{ metricClass: 'periodic' }} onChange={onChange} />)

    const select = document.querySelectorAll('.ant-select')[0]
    // ⚠️ antd 的 Select 是 **mousedown** 打开下拉，不是 click
    fireEvent.mouseDown(select.querySelector('.ant-select-selector') as HTMLElement)
    const option = [...document.querySelectorAll('.ant-select-item-option')].find(
      // ⚠️ 显示的是中文标签，但**选中后传回的是原始算法名**
      (el) => el.textContent === detectorLabel('mad'),
    )
    expect(option).toBeTruthy()
    fireEvent.click(option as HTMLElement)

    expect(onChange).toHaveBeenCalledWith({ metricClass: 'periodic', detector: 'mad' })
  })

  it('有筛选时才出现「重置」', () => {
    const { rerender } = render(<FilterBar rows={rows} filters={{}} onChange={() => {}} />)
    expect(
      [...document.querySelectorAll('button')].some((b) => b.textContent.replace(/\s/g, '') === '重置'),
    ).toBe(false)

    rerender(<FilterBar rows={rows} filters={{ detector: 'iqr' }} onChange={() => {}} />)
    expect(
      [...document.querySelectorAll('button')].some((b) => b.textContent.replace(/\s/g, '') === '重置'),
    ).toBe(true)
  })
})
