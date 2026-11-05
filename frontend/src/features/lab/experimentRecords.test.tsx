/**
 * 实验记录列表 + 一键建任务。
 *
 * ⚠️ 这一块的价值在**可复现** —— 记录要能看出「当时跑的是什么、结论是什么」。
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ExperimentRecords } from './ExperimentRecords'
import type { LabExperimentSummary } from '../../api/types'

function _record(overrides: Partial<LabExperimentSummary> = {}): LabExperimentSummary {
  return {
    id: '20261104-120000-abc123',
    created_at: '2026-11-04T12:00:00.123456+00:00',
    fingerprint: 'sha256:0123456789abcdef',
    spec: {
      kind: 'metric',
      metric_id: 1,
      metric_name: 'demo-metric',
      source_id: 1,
      freq: '5min',
      start: '2026-11-01T00:00:00+00:00',
      end: '2026-11-04T00:00:00+00:00',
      sampling: {
        mode: 'even',
        window_points: 200,
        stride_points: 200,
        max_points: 2000,
        max_windows: 10,
        min_valid_ratio: 0.8,
        seed: 42,
      },
      detectors: ['auto'],
      multipliers: [1.5, 2.5],
    },
    summary: {
      n_windows: 4,
      detectors: [
        {
          detector: 'auto',
          n_windows: 4,
          n_alerts: 20,
          alert_ratio: 0.025,
          stability: 0.03,
        },
      ],
      warnings: [],
    },
    ...overrides,
  }
}

describe('ExperimentRecords', () => {
  it('列出记录的关键信息', () => {
    render(<ExperimentRecords records={[_record()]} onCreateJob={() => {}} />)

    expect(screen.getByText('demo-metric')).toBeInTheDocument()
    expect(screen.getByText(/200 点 × 4 窗/)).toBeInTheDocument()
    expect(screen.getByText(/自动推荐 20/)).toBeInTheDocument()
    // 指纹只展示短片段，完整值在 title 里
    expect(screen.getByText('0123456789ab')).toBeInTheDocument()
  })

  it('点「一键建任务」把记录 id 交回去', async () => {
    const user = userEvent.setup()
    const onCreateJob = vi.fn()
    render(<ExperimentRecords records={[_record()]} onCreateJob={onCreateJob} />)

    await user.click(screen.getByRole('button', { name: '一键建任务' }))

    expect(onCreateJob).toHaveBeenCalledWith('20261104-120000-abc123')
  })

  it('临时 SQL 的记录不给建任务（按钮禁用）', () => {
    const record = _record()
    record.spec.kind = 'sql'

    render(<ExperimentRecords records={[record]} onCreateJob={() => {}} />)

    expect(screen.getByRole('button', { name: '一键建任务' })).toBeDisabled()
  })

  it('没有记录时给出提示', () => {
    render(<ExperimentRecords records={[]} onCreateJob={() => {}} />)

    expect(screen.getByText('还没有保存过实验记录')).toBeInTheDocument()
  })
})
