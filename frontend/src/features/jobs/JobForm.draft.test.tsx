/**
 * 「一键建任务」的草稿回填 —— 实验结论要真的落到表单里。
 *
 * ⚠️ 这条链路是 P2 的落点：实验 → 草稿 → 任务表单。
 *    回填错了，实验的结论就白做了。
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { JobForm } from './JobForm'
import type { CatalogDetector, CatalogMetric } from '../../api/types'

const detector: CatalogDetector = {
  name: 'iqr',
  default_threshold: 2.5,
  score_type: 'zscore',
  label: 'iqr',
}

const metric: CatalogMetric = {
  id: 7,
  source_id: 1,
  name: 'demo-metric',
  query: 'SELECT ts, value FROM m',
  time_column: 'ts',
  value_column: 'value',
  group_column: null,
  time_format: 'iso_utc',
  freq: '5min',
  source_timezone: 'UTC',
  missing_policy: 'drop',
  created_at: '2026-10-30T00:00:00+00:00',
}

describe('JobForm 的草稿回填', () => {
  it('按实验结论预填指标、算法、窗口与执行间隔', async () => {
    render(
      <JobForm
        open
        metrics={[metric]}
        detectors={[detector]}
        onCancel={() => {}}
        onSubmit={() => {}}
        initialValues={{
          metric_id: 7,
          name: 'demo-metric 巡检',
          detector: 'iqr',
          window_points: 200,
          interval_seconds: 300,
          alert_rules: [
            { multiplier: 2.5, level: 'P1' },
            { multiplier: 3.75, level: 'P0' },
          ],
        }}
      />,
    )

    await waitFor(() => expect(screen.getByLabelText(/任务名称/)).toHaveValue('demo-metric 巡检'))
    expect(screen.getByLabelText(/窗口点数/)).toHaveValue('200')
    expect(screen.getByLabelText(/执行间隔/)).toHaveValue('300')
    // 指标与算法是 AntD 的 Select —— 选中项的文本要出现在表单里
    expect(screen.getByTitle('demo-metric')).toBeInTheDocument()
    expect(screen.getByText(/IQR 围栏/)).toBeInTheDocument()
  })

  it('回填的告警规则带进提交载荷', async () => {
    const user = userEvent.setup({ delay: null })
    const onSubmit = vi.fn()
    render(
      <JobForm
        open
        metrics={[metric]}
        detectors={[detector]}
        onCancel={() => {}}
        onSubmit={onSubmit}
        initialValues={{
          metric_id: 7,
          name: 'demo-metric 巡检',
          detector: 'iqr',
          window_points: 200,
          interval_seconds: 300,
          alert_rules: [{ multiplier: 2.5, level: 'P1' }],
        }}
      />,
    )

    await waitFor(() => expect(screen.getByLabelText(/任务名称/)).toHaveValue('demo-metric 巡检'))
    await user.click(screen.getByRole('button', { name: '创 建' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit.mock.calls[0][0].alert_rules).toEqual([{ multiplier: 2.5, level: 'P1' }])
    expect(onSubmit.mock.calls[0][0].window_points).toBe(200)
  })

  it('没有草稿时表单是空的', async () => {
    render(
      <JobForm open metrics={[metric]} detectors={[detector]} onCancel={() => {}} onSubmit={() => {}} />,
    )

    await waitFor(() => expect(screen.getByLabelText(/任务名称/)).toHaveValue(''))
  })
})
