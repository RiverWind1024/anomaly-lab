import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import type { EvaluationRow, Summary } from '../../api/types'
import { EvaluationTable, fmtMetric } from './EvaluationPage'

const row: EvaluationRow = {
  series_id: 'demo-1',
  metric_class: 'periodic',
  detector: 'iqr',
  score_type: 'zscore',
  threshold: 2.5,
  precision: 1,
  recall: 0.5,
  f1: 0.667,
  range_f1: 0.5,
  n_truth: 2,
  n_pred: 1,
  elapsed_ms: 0.1,
}

const summary: Summary = {
  generated_at: '2026-10-29T00:00:00+00:00',
  title: '回测',
  summary: {
    overall: {
      n_series: 1,
      n_truth: 2,
      n_pred: 1,
      precision: 0.5,
      recall: 0.5,
      f1: 0.5,
      range_f1: 0.4,
      elapsed_ms: 0.1,
    },
  },
  rows: [row],
}

describe('fmtMetric', () => {
  it('保留三位小数', () => {
    expect(fmtMetric(0.5)).toBe('0.500')
  })

  it('非有限值显示「—」', () => {
    expect(fmtMetric(NaN)).toBe('—')
    expect(fmtMetric(null)).toBe('—')
    expect(fmtMetric(undefined)).toBe('—')
  })
})

/** EvaluationTable 里有 react-router 的 Link —— 必须包 Router。 */
function renderTable(node: ReactElement) {
  return render(<MemoryRouter>{node}</MemoryRouter>)
}

describe('EvaluationTable', () => {
  it('原有 9 列一个都不能少（另加一列操作）', () => {
    renderTable(
      <EvaluationTable
        isLoading={false}
        error={null}
        summary={summary}
        excludedCount={0}
        onOpenExcluded={() => {}}
        onExclude={() => {}}
      />,
    )
    // 明细表与聚合表都有表头 —— 只看明细表的
    const detail = document.querySelector('.evaluation__detail') as HTMLElement
    const headers = within(detail)
      .getAllByRole('columnheader')
      .map((th) => th.textContent ?? '')
      .filter((text, index, all) => all.indexOf(text) === index)
    expect(headers).toEqual([
      '序列',
      '形态',
      '检测器',
      'Precision',
      'Recall',
      'F1',
      'Range-F1',
      '真值点',
      '预测点',
      '操作',
    ])
  })

  it('总体行显示 precision / recall / f1 / range_f1', () => {
    renderTable(
      <EvaluationTable
        isLoading={false}
        error={null}
        summary={summary}
        excludedCount={0}
        onOpenExcluded={() => {}}
        onExclude={() => {}}
      />,
    )
    const overall = document.querySelector('.evaluation__overall')
    expect(overall?.textContent).toContain('0.500')
    expect(overall?.textContent).toContain('0.400')
  })

  it('没有报告时显示「暂无报告，请先运行 evaluate」', () => {
    renderTable(
      <EvaluationTable
        isLoading={false}
        error={null}
        summary={{ ...summary, rows: [], summary: {} }}
        excludedCount={0}
        onOpenExcluded={() => {}}
        onExclude={() => {}}
      />,
    )
    expect(screen.getByText('暂无报告，请先运行 evaluate')).toBeTruthy()
  })

  it('序列列链到检测记录页', () => {
    renderTable(
      <EvaluationTable
        isLoading={false}
        error={null}
        summary={summary}
        excludedCount={0}
        onOpenExcluded={() => {}}
        onExclude={() => {}}
      />,
    )
    const link = screen.getByText('demo-1') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/detections?series_id=demo-1')
  })
})
