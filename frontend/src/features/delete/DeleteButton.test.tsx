import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Catalog } from '../../api/types'
import { DeleteButton } from './DeleteButton'
import { impactText } from './impact'

const catalog: Catalog = {
  sources: [
    {
      id: 1,
      name: 'local',
      kind: 'sqlite',
      path: 'p.db',
      created_at: '2026-10-30T00:00:00+00:00',
    },
  ],
  metrics: [
    {
      id: 10,
      source_id: 1,
      name: 'm1',
      query: 'q',
      time_column: 'ts',
      value_column: 'value',
      group_column: null,
      time_format: 'iso_utc',
      freq: '5min',
      source_timezone: 'UTC',
      missing_policy: 'drop',
      created_at: '2026-10-30T00:00:00+00:00',
    },
  ],
  jobs: [
    {
      id: 100,
      metric_id: 10,
      name: 'j1',
      detector: 'iqr',
      alert_threshold: 2.5,
      critical_threshold: 3.75,
      window_points: 300,
      interval_seconds: 300,
      enabled: true,
      last_run_at: null,
      next_run_at: null,
      created_at: '2026-10-30T00:00:00+00:00',
      alert_rules: [],
    },
  ],
  detectors: [],
}

describe('impactText', () => {
  it('数据源要说明会连带删多少指标与任务', () => {
    expect(impactText('source', 1, catalog)).toBe('将连带删除 1 个指标、1 个任务')
  })

  it('指标要说明会连带删多少任务', () => {
    expect(impactText('metric', 10, catalog)).toBe('将连带删除 1 个任务')
  })

  it('任务没有依赖时只说删任务本身', () => {
    expect(impactText('job', 100, catalog)).toBe('将删除该任务')
  })

  it('没有依赖时不提数字', () => {
    const empty: Catalog = { ...catalog, metrics: [], jobs: [] }
    expect(impactText('source', 1, empty)).toBe('将删除该数据源')
    expect(impactText('metric', 10, empty)).toBe('将删除该指标')
  })

  it('只统计该数据源下面的指标，不串到别的数据源', () => {
    const twoSources: Catalog = {
      ...catalog,
      sources: [
        ...catalog.sources,
        {
          id: 2,
          name: 'other',
          kind: 'sqlite',
          path: 'o.db',
          created_at: '2026-10-30T00:00:00+00:00',
        },
      ],
      metrics: [
        ...catalog.metrics,
        {
          ...catalog.metrics[0],
          id: 11,
          source_id: 2,
          name: 'm2',
        },
      ],
    }
    expect(impactText('source', 2, twoSources)).toBe('将连带删除 1 个指标')
    expect(impactText('source', 1, twoSources)).toBe('将连带删除 1 个指标、1 个任务')
  })
})

describe('DeleteButton', () => {
  it('确认弹窗写明连带删除的数量', async () => {
    const user = userEvent.setup({ delay: null })
    render(
      <DeleteButton
        target="source"
        id={1}
        name="local"
        catalog={catalog}
        onConfirm={() => {}}
      />,
    )
    // ⚠️ antd 的中文两字按钮会自动插空格（「删 除」）→ 用正则
    await user.click(screen.getByRole('button', { name: /删\s*除/ }))
    expect(await screen.findByText(/将连带删除 1 个指标、1 个任务/)).toBeTruthy()
  })

  it('确认弹窗写明要删的对象名', async () => {
    const user = userEvent.setup({ delay: null })
    render(
      <DeleteButton
        target="job"
        id={100}
        name="j1"
        catalog={catalog}
        onConfirm={() => {}}
      />,
    )
    await user.click(screen.getByRole('button', { name: /删\s*除/ }))
    expect(await screen.findByText(/确定删除任务「j1」/)).toBeTruthy()
  })
})
