import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Summary } from '../../api/types'
import { EvaluationPage } from './EvaluationPage'

/**
 * 报告数据。刻意给两个形态（一好一差），结论句才有内容可断言。
 */
const summary: Summary = {
  generated_at: '2026-10-29T00:00:00+00:00',
  title: '回测',
  summary: {
    overall: {
      n_series: 2,
      n_truth: 6,
      n_pred: 4,
      precision: 0.5,
      recall: 0.6,
      f1: 0.5,
      range_f1: 0.4,
      elapsed_ms: 0.2,
    },
    by_metric_class: {
      periodic: {
        n_series: 1,
        n_truth: 3,
        n_pred: 2,
        precision: 0.7,
        recall: 0.7,
        f1: 0.7,
        range_f1: 0.6,
        elapsed_ms: 0.1,
      },
      spike: {
        n_series: 1,
        n_truth: 3,
        n_pred: 2,
        precision: 0.3,
        recall: 0.3,
        f1: 0.3,
        range_f1: 0.2,
        elapsed_ms: 0.1,
      },
    },
  },
  rows: [
    {
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
    },
  ],
}

/** 取数状态可在用例之间切换（验证「加载中」与数据到达后的页头）。 */
const state = vi.hoisted(() => ({
  pending: false,
  data: undefined as Summary | undefined,
}))

vi.mock('./queries', () => ({
  useSummary: () => ({ isPending: state.pending, error: null, data: state.data }),
  useExcludeEvaluationRow: () => ({ mutate: vi.fn(), isPending: false }),
  useRestoreEvaluationRow: () => ({ mutate: vi.fn(), isPending: false }),
}))

// 生产面板自己取数，这里只验证「视图挂对了位置」，不重复测它的内部结构。
vi.mock('./ProductionEvaluationPanel', () => ({
  ProductionEvaluationPanel: () => <div data-testid="production-panel">生产评估面板</div>,
}))

/** 把当前 URL 打出来，供断言 tab 是否写回地址栏。 */
function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location">{location.search}</span>
}

function renderPage(route = '/evaluation') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <LocationProbe />
      <EvaluationPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  state.pending = false
  state.data = summary
})

describe('EvaluationPage 视图切换', () => {
  it('默认是离线回测：结论行 + 分组 + 明细都在，生产面板不渲染', () => {
    const { container } = renderPage()

    const offline = screen.getByRole('tab', { name: '离线回测' })
    expect(offline.getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('.evaluation__conclusion')).toBeTruthy()
    expect(container.querySelector('.evaluation__detail')).toBeTruthy()
    expect(screen.queryByTestId('production-panel')).toBeNull()
  })

  it('不带 tab 参数的旧链接按离线回测处理', () => {
    renderPage('/evaluation?series_id=demo-1')
    expect(screen.getByRole('tab', { name: '离线回测' }).getAttribute('aria-selected')).toBe(
      'true',
    )
    expect(screen.queryByTestId('production-panel')).toBeNull()
  })

  it('?tab=production 直接打开生产评估，且不重复离线 KPI / 明细', () => {
    const { container } = renderPage('/evaluation?tab=production')

    expect(screen.getByRole('tab', { name: '生产评估' }).getAttribute('aria-selected')).toBe(
      'true',
    )
    expect(screen.getByTestId('production-panel')).toBeTruthy()
    expect(screen.queryByText(/人工标注 × 线上运行/)).toBeTruthy()
    // 生产视图里不能混进离线回测的东西
    expect(container.querySelector('.evaluation__conclusion')).toBeNull()
    expect(container.querySelector('.evaluation__detail')).toBeNull()
  })

  it('点击「生产评估」把 tab 写进 URL', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('tab', { name: '生产评估' }))

    expect(screen.getByTestId('location').textContent).toBe('?tab=production')
    expect(screen.getByTestId('production-panel')).toBeTruthy()
  })
})

describe('EvaluationPage 页头', () => {
  it('标题下只有一行：报告是什么 + 生成时间', () => {
    renderPage()

    const header = document.querySelector('.page__header') as HTMLElement
    // 副标题只有一行，且同时包含口径与生成时间
    const lines = header.querySelectorAll('p')
    expect(lines).toHaveLength(1)
    expect(lines[0].textContent).toContain('回测报告')
    expect(lines[0].textContent).toContain('生成于')
  })

  it('数据未到时显示「加载中…」，仍占住同一行', () => {
    state.pending = true
    state.data = undefined
    renderPage()

    const provenance = document.querySelector('.evaluation__provenance') as HTMLElement
    expect(provenance.textContent).toBe('加载中…')
  })
})
