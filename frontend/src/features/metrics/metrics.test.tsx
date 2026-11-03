import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogMetric, CatalogSource } from '../../api/types'
import { MetricList } from './MetricList'
import {
  DEFAULT_METRIC_QUERY,
  MISSING_POLICY_OPTIONS,
  TIME_FORMAT_OPTIONS,
} from './MetricFormFields'

const source: CatalogSource = {
  id: 1,
  name: 'local',
  kind: 'sqlite',
  path: 'platform/source.db',
  created_at: '2026-10-30T00:00:00+00:00',
}

const metric: CatalogMetric = {
  id: 1,
  source_id: 1,
  name: 'demo-metric',
  query: DEFAULT_METRIC_QUERY,
  time_column: 'ts',
  value_column: 'value',
  group_column: 'host',
  time_format: 'iso_utc',
  freq: '5min',
  source_timezone: 'UTC',
  missing_policy: 'drop',
  created_at: '2026-10-30T00:00:00+00:00',
}

describe('指标表单的枚举值', () => {
  it('时间格式取值与后端 TimeFormat 一致', () => {
    // 后端：Literal["iso_utc", "iso_naive", "epoch_s", "epoch_ms"]
    expect(TIME_FORMAT_OPTIONS.map((o) => o.value)).toEqual([
      'iso_utc',
      'iso_naive',
      'epoch_s',
      'epoch_ms',
    ])
  })

  it('缺失值策略取值与后端 MissingPolicy 一致', () => {
    // 后端：Literal["drop", "interpolate", "error"]
    expect(MISSING_POLICY_OPTIONS.map((o) => o.value)).toEqual([
      'drop',
      'interpolate',
      'error',
    ])
  })

  it('默认查询语句保留 $timefilter 占位符（前端不替换）', () => {
    expect(DEFAULT_METRIC_QUERY).toContain('$timefilter')
    expect(DEFAULT_METRIC_QUERY).toContain('ORDER BY ts')
  })
})

describe('MetricList', () => {
  /** 列表组件现在带删除入口，测试要传齐 props。 */
  const listProps = {
    catalog: undefined,
    onDelete: () => {},
    deletingId: null,
    onEdit: () => {},
  }

  it('列：ID / 名称 / 数据源 / 分组列 / 时间列 / 值列 / 频率 / 时区 / 缺失 / 操作', () => {
    render(
      // ⚠️ MetricList 里有 react-router 的 useNavigate —— 必须包 Router
      <MemoryRouter>
        <MetricList
          isLoading={false}
          error={null}
          metrics={[metric]}
          sources={[source]}
          {...listProps}
        />
      </MemoryRouter>,
    )
    // AntD 会额外渲染一行隐藏的测量用表头，所以同一个标题有两个元素 ——
    // 按 columnheader 角色取，并去掉重复。
    const headers = screen
      .getAllByRole('columnheader')
      .map((th) => th.textContent ?? '')
      .filter((text, index, all) => all.indexOf(text) === index)
    expect(headers).toEqual([
      'ID',
      '名称',
      '数据源',
      '分组列',
      '时间列',
      '值列',
      '频率',
      '时区',
      '缺失',
      '操作',
    ])
  })

  it('数据源列显示名字而不是 id', () => {
    render(
      // ⚠️ MetricList 里有 react-router 的 useNavigate —— 必须包 Router
      <MemoryRouter>
        <MetricList
          isLoading={false}
          error={null}
          metrics={[metric]}
          sources={[source]}
          {...listProps}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('local')).toBeTruthy()
  })

  it('没有分组列时显示占位', () => {
    render(
      <MemoryRouter>
        <MetricList
          isLoading={false}
          error={null}
          metrics={[{ ...metric, group_column: null }]}
          sources={[source]}
          {...listProps}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('—')).toBeTruthy()
  })

  it('空列表显示空态', () => {
    render(
      <MemoryRouter>
        <MetricList
          isLoading={false}
          error={null}
          metrics={[]}
          sources={[]}
          {...listProps}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('还没有指标')).toBeTruthy()
  })

  it('列表有「编辑」按钮 —— 点它进独立编辑页', () => {
    const onEdit = vi.fn()
    render(
      <MemoryRouter>
        <MetricList
          isLoading={false}
          error={null}
          metrics={[metric]}
          sources={[source]}
          {...listProps}
          onEdit={onEdit}
        />
      </MemoryRouter>,
    )
    // ⚠️ antd 的 Button 在两个字之间插空格 —— 断言要容得下
    const button = screen.getByRole('button', { name: /编\s*辑/ })
    expect(button).toBeTruthy()
    fireEvent.click(button)
    expect(onEdit).toHaveBeenCalledWith(metric)
  })
})
