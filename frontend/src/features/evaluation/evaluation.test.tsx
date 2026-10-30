import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import type { Badcases, EvaluationRow, Summary } from '../../api/types'
import { EvaluationTable, fmtMetric } from './EvaluationPage'
import { badcaseLabel, buildBadcaseOption, toRanges } from './BadcasesPage'

const badcases: Badcases = {
  series_id: 'demo-1',
  detector: 'iqr',
  threshold: 2.5,
  score_type: 'zscore',
  timestamps: ['t0', 't1', 't2', 't3', 't4'],
  values: [1, 2, 3, 4, 5],
  scores: [0.1, 0.2, 3.1, 0.4, 0.5],
  badcases: [
    {
      kind: 'false_positive',
      group: 'periodic/中段/孤立点',
      reason: '误报：形态=periodic，位置=中段，孤立点',
      indices: [2],
    },
    {
      kind: 'false_negative',
      group: 'periodic/前10%/连续段',
      reason: '漏报：形态=periodic，位置=前10%，连续段',
      indices: [0, 1],
    },
  ],
}

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

describe('toRanges', () => {
  it('连续索引压成一个区间', () => {
    expect(toRanges([0, 1, 2])).toEqual([[0, 2]])
  })

  it('不连续的索引拆成多个区间', () => {
    expect(toRanges([0, 1, 4, 5, 9])).toEqual([
      [0, 1],
      [4, 5],
      [9, 9],
    ])
  })

  it('乱序输入也能正确分段', () => {
    expect(toRanges([3, 1, 2])).toEqual([[1, 3]])
  })

  it('空数组返回空', () => {
    expect(toRanges([])).toEqual([])
  })
})

describe('buildBadcaseOption', () => {
  it('⚠️ 用 badcases[].indices 真正画出异常区间（旧版是空对象 markArea，等于没画）', () => {
    const option = buildBadcaseOption({ data: badcases })
    const areas = option.series[0].markArea?.data as Array<Array<{ xAxis: number }>>
    expect(areas).toHaveLength(2)
    // 误报区间 [2,2]
    expect(areas[0][0].xAxis).toBe(2)
    expect(areas[0][1].xAxis).toBe(2)
    // 漏报区间 [0,1]
    expect(areas[1][0].xAxis).toBe(0)
    expect(areas[1][1].xAxis).toBe(1)
  })

  it('每个区间都带颜色', () => {
    const option = buildBadcaseOption({ data: badcases })
    const areas = option.series[0].markArea?.data as Array<
      Array<{ xAxis: number; itemStyle?: { color?: string } }>
    >
    for (const area of areas) {
      expect(area[0].itemStyle?.color).toBeTruthy()
    }
  })

  it('没有 badcase 时 markArea 是空数组（不是空对象）', () => {
    const option = buildBadcaseOption({ data: { ...badcases, badcases: [] } })
    expect(option.series[0].markArea?.data).toEqual([])
  })

  it('三条线：数值 / 分数 / 阈值', () => {
    const option = buildBadcaseOption({ data: badcases })
    expect(option.series.map((s) => s.name)).toEqual(['数值', '分数', '阈值'])
  })

  it('阈值线挂在分数轴上', () => {
    const option = buildBadcaseOption({ data: badcases })
    const threshold = option.series.find((s) => s.name === '阈值')
    expect(threshold?.yAxisIndex).toBe(1)
  })

  it('分数线也挂在分数轴上', () => {
    const option = buildBadcaseOption({ data: badcases })
    expect(option.series.find((s) => s.name === '分数')?.yAxisIndex).toBe(1)
  })
})

describe('badcaseLabel', () => {
  it('误报与漏报有中文名', () => {
    expect(badcaseLabel('false_positive')).toBe('误报')
    expect(badcaseLabel('false_negative')).toBe('漏报')
  })

  it('未知类型原样显示', () => {
    expect(badcaseLabel('whatever')).toBe('whatever')
  })
})

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
  it('9 列一个都不能少', () => {
    renderTable(<EvaluationTable isLoading={false} error={null} summary={summary} />)
    const headers = screen
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
    ])
  })

  it('总体行显示 precision / recall / f1 / range_f1', () => {
    renderTable(<EvaluationTable isLoading={false} error={null} summary={summary} />)
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
      />,
    )
    expect(screen.getByText('暂无报告，请先运行 evaluate')).toBeTruthy()
  })

  it('序列列链到 Bad Case 页', () => {
    renderTable(<EvaluationTable isLoading={false} error={null} summary={summary} />)
    const link = screen.getByText('demo-1') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/badcases?series_id=demo-1')
  })
})
