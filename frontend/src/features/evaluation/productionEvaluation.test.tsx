import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { ProductionEvaluation } from '../../api/types'

const { result } = vi.hoisted(() => ({
  result: {
  rows: [
    {
      run_id: 9320,
      series_id: 'demo-metric:web-api',
      group: 'web-api',
      job_id: 2,
      detector: 'seasonal',
      source_id: 1,
      source_name: 'demo-sqlite',
      metric_id: 1,
      metric_name: 'demo-metric',
      outcome: 'alert' as const,
      outcome_label: '异常',
      start_ts: '2026-10-28T16:03:00',
      end_ts: '2026-10-30T09:38:00',
      n: 500,
      n_truth: 2,
      n_pred: 25,
      n_annotations: 1,
      rate: 0.2,
      weight: 5,
      tp: 2,
      fp: 23,
      fn: 0,
      precision: 0.08,
      recall: 1,
      f1: 0.148,
      range_f1: 0.294,
    },
  ],
  layers: [
    {
      source_id: 1,
      source_name: 'demo-sqlite',
      metric_id: 1,
      metric_name: 'demo-metric',
      outcome: 'alert' as const,
      outcome_label: '异常',
      n_candidates: 9,
      n_contents: 9,
      n_events: 2,
      n_sampled: 5,
      n_annotated: 1,
      rate: 0.2,
      precision: 0.08,
      recall: 1,
      f1: 0.148,
      range_f1: 0.294,
    },
    {
      source_id: 1,
      source_name: 'demo-sqlite',
      metric_id: 1,
      metric_name: 'demo-metric',
      outcome: 'normal' as const,
      outcome_label: '正常',
      n_candidates: 40,
      n_contents: 40,
      n_events: 0,
      n_sampled: 2,
      n_annotated: 0,
      rate: 0.05,
      precision: null,
      recall: null,
      f1: null,
      range_f1: 0,
    },
  ],
  overall: {
    n_samples: 1,
    n_layers: 1,
    precision: 0.08,
    recall: 1,
    f1: 0.148,
    range_f1: 0.294,
    n_truth: 2,
    n_alerts: 25,
    n_estimated: 125,
    tp: 10,
    fp: 115,
    fn: 0,
  },
  sampling: {
    rate_alert: 0.5,
    rate_normal: 0.05,
    n_candidates: 49,
    n_sampled: 7,
    n_annotated: 1,
    max_per_layer: 10,
    n_events: 2,
    layers: [],
  },
  n_candidates: 49,
  warnings: [
    '采样出的 7 条里还有 6 条没标 —— 下面的成绩只覆盖被标注过的那部分，不代表整体效果',
  ],
  } as ProductionEvaluation,
}))

vi.mock('./queries', () => ({
  useProductionEvaluation: () => ({ isPending: false, error: null, data: result }),
}))

async function renderPanel() {
  const { ProductionEvaluationPanel } = await import('./ProductionEvaluationPanel')
  return render(
    <MemoryRouter>
      <ProductionEvaluationPanel />
    </MemoryRouter>,
  )
}

describe('ProductionEvaluationPanel', () => {
  it('标题写明是生产检测记录', async () => {
    await renderPanel()
    expect(screen.getByRole('heading', { name: '生产检测记录' })).toBeTruthy()
  })

  it('分层维度是数据源 → 指标 → 检出结果', async () => {
    await renderPanel()
    expect(screen.getByRole('heading', { name: '分层表现' })).toBeTruthy()
    // ⚠️ 数据源 / 指标名在分层表与明细表里都会出现 —— 用「至少有一个」。
    expect(screen.getAllByText('demo-sqlite').length).toBeGreaterThan(0)
    expect(screen.getAllByText('demo-metric').length).toBeGreaterThan(0)
    // ⚠️ 正常层与异常层**分开** —— 漏报只能从正常记录里发现。
    expect(screen.getAllByText('异常').length).toBeGreaterThan(0)
    expect(screen.getAllByText('正常').length).toBeGreaterThan(0)
  })

  it('说清楚成绩只覆盖被标注过的那部分', async () => {
    await renderPanel()
    // ⚠️ 只给一个漂亮的 F1 是在骗人 —— 未标注的占比必须说出来。
    expect(document.body.textContent).toContain('只覆盖被标注过的那部分')
  })

  it('候选 / 告警事件 / 采样 / 已标注四个数一起给出', async () => {
    await renderPanel()
    expect(screen.getAllByText('候选').length).toBeGreaterThan(0)
    expect(screen.getAllByText('告警事件').length).toBeGreaterThan(0)
    expect(screen.getAllByText('采样').length).toBeGreaterThan(0)
    expect(screen.getAllByText('已标注').length).toBeGreaterThan(0)
    expect(document.body.textContent).toContain('全部运行记录 × 全部序列')
  })

  it('告警事件数与检测记录数分开 —— 同一区间反复报出只算一个', async () => {
    await renderPanel()
    expect(document.body.textContent).toContain('同一区间只算一个')
  })

  it('正常层与异常层各有一个采样率', async () => {
    await renderPanel()
    expect(screen.getByText('异常层')).toBeTruthy()
    expect(screen.getByText('正常层')).toBeTruthy()
    expect(screen.getByText('每层最多')).toBeTruthy()
  })
})
