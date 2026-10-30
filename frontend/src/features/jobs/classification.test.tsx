import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AlertRulesView } from './AlertRulesView'
import { ClassificationCard, metricClassLabel } from './ClassificationCard'

describe('metricClassLabel', () => {
  it('6 种形态都有中文标签', () => {
    expect(metricClassLabel('stationary')).toBe('平稳型')
    expect(metricClassLabel('periodic')).toBe('周期型')
    expect(metricClassLabel('trending')).toBe('趋势型')
    expect(metricClassLabel('step')).toBe('阶梯型')
    expect(metricClassLabel('high_zero_ratio')).toBe('高零值比例型')
    expect(metricClassLabel('sparse_event')).toBe('稀疏事件型')
  })

  it('空值显示「未判定」', () => {
    expect(metricClassLabel('')).toBe('未判定')
    expect(metricClassLabel(null)).toBe('未判定')
  })

  it('未登记的形态原样显示（宁可显示原始标识也不要错的翻译）', () => {
    expect(metricClassLabel('something_new')).toBe('something_new')
  })
})

describe('ClassificationCard', () => {
  const base = {
    metricClass: 'periodic',
    confidence: 0.8339,
    reasons: ['趋势强度 0.31 < 0.60 → 排除趋势残留', '主导周期 24'],
    autoDetector: 'seasonal',
    autoRationale: '周期型需要按相位分组或先做 STL 分解',
    autoFallback: false,
    scoreType: 'residual_ratio',
  }

  it('展示形态、置信度、自动选用与分数类型', () => {
    render(<ClassificationCard {...base} />)
    expect(screen.getByText('周期型')).toBeTruthy()
    expect(screen.getByText('0.83')).toBeTruthy()
    expect(screen.getByText('seasonal')).toBeTruthy()
    expect(screen.getByText('residual_ratio')).toBeTruthy()
  })

  it('展示判定依据与推荐理由', () => {
    render(<ClassificationCard {...base} />)
    expect(screen.getByText(/排除趋势残留/)).toBeTruthy()
    expect(screen.getByText(/STL 分解/)).toBeTruthy()
  })

  it('回退时打「回退」标记', () => {
    render(<ClassificationCard {...base} autoFallback />)
    expect(screen.getByText('回退')).toBeTruthy()
  })

  it('没有理由时不渲染依据区', () => {
    render(<ClassificationCard {...base} reasons={[]} />)
    expect(screen.queryByText('判定依据')).toBeNull()
  })
})

describe('AlertRulesView', () => {
  it('逐条列出规则', () => {
    render(
      <AlertRulesView
        rules={[
          { multiplier: 2.5, level: 'P1' },
          { op: '>', value: 50, level: 'P0' },
        ]}
      />,
    )
    expect(screen.getByText('P1')).toBeTruthy()
    expect(screen.getByText('P0')).toBeTruthy()
    expect(screen.getByText('× 2.5')).toBeTruthy()
    expect(screen.getByText('> 50')).toBeTruthy()
  })

  it('没有规则时说明用默认两档，并提示规则只读', () => {
    render(<AlertRulesView rules={null} />)
    expect(screen.getByText('未设置告警规则')).toBeTruthy()
    expect(screen.getByText(/默认两档/)).toBeTruthy()
    expect(screen.getByText(/规则只读/)).toBeTruthy()
  })

  it('空数组也走「未设置」分支', () => {
    render(<AlertRulesView rules={[]} />)
    expect(screen.getByText('未设置告警规则')).toBeTruthy()
  })
})
