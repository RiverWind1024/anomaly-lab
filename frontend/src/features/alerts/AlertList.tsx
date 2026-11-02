import { useState } from 'react'
import { Alert, Button, DatePicker, Select, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { AlertDetailDrawer } from './AlertDetailDrawer'
import type { AlertEvent, AlertListResponse } from '../../api/types'
import type { AlertFilters } from './queries'

export interface AlertListProps {
  isLoading: boolean
  error: unknown
  data: AlertListResponse | undefined
  filters: AlertFilters
  onFiltersChange: (next: AlertFilters) => void
}

/**
 * 等级 → 状态色。
 *
 * ⚠️ 用 `level_index` 而不是档位名 —— 档位名是自定义的（「注意」「P0」），
 *    没法按名字判严重度。
 *
 * ⚠️ 只有两档颜色：P0（level_index ≥ 2）与其余。
 *    告警三档是平台定死的，不能另起颜色。
 */
function levelPill(levelIndex: number, level: string) {
  return (
    <span className={`pill ${levelIndex >= 2 ? 'pill--p0' : 'pill--p1'}`}>{level}</span>
  )
}

/**
 * 时间区间。
 *
 * ⚠️ 同一天时只显示一次日期 —— 否则「2026-10-30 09:23 ~ 2026-10-30 09:23」
 *    在窄列里会折成两行，把表格撑得很丑。
 */
function fmtRange(start: string, end: string): string {
  const from = start.replace('T', ' ').slice(5, 16)
  const to = end.replace('T', ' ').slice(5, 16)
  if (start.slice(0, 10) === end.slice(0, 10)) {
    return `${from} ~ ${end.replace('T', ' ').slice(11, 16)}`
  }
  return `${from} ~ ${to}`
}

export function AlertList({ isLoading, error, data, filters, onFiltersChange }: AlertListProps) {
  const [detail, setDetail] = useState<AlertEvent | null>(null)

  const columns: ColumnsType<AlertEvent> = [
    {
      title: '等级',
      dataIndex: 'level',
      key: 'level',
      width: 90,
      render: (value: string, row) => levelPill(row.level_index, value),
    },
    {
      title: '时间',
      key: 'time',
      width: 190,
      render: (_value, row) => (
        <span className="mono">{fmtRange(row.start_ts, row.end_ts)}</span>
      ),
    },
    {
      title: '点数',
      dataIndex: 'n_points',
      key: 'n_points',
      width: 80,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '峰值 σ',
      dataIndex: 'max_score',
      key: 'max_score',
      width: 110,
      align: 'right',
      render: (value: number) => <span className="mono">{value.toFixed(2)}</span>,
    },
    {
      title: '任务',
      dataIndex: 'job_name',
      key: 'job_name',
      width: 180,
      render: (value: string, row) => <Link to={`/jobs/${row.job_id}`}>{value}</Link>,
    },
    {
      title: '序列',
      dataIndex: 'series_id',
      key: 'series_id',
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '算法',
      dataIndex: 'detector',
      key: 'detector',
      width: 130,
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      // ⚠️ 固定在右侧 —— 列多的时候横向滚动，否则「详情」按钮会被推出屏幕外
      fixed: 'right',
      render: (_value, row) => (
        <Button size="small" onClick={() => setDetail(row)}>
          详情
        </Button>
      ),
    },
  ]

  const hasFilters =
    filters.jobId !== undefined ||
    filters.level !== undefined ||
    filters.seriesId !== undefined ||
    filters.since !== undefined ||
    filters.until !== undefined

  return (
    <StateBoundary
      isLoading={isLoading}
      error={error}
      data={data}
      // ⚠️ 「一个任务都没有」才是空态；「有任务但没告警」要显示「当前没有告警」
      isEmpty={(d) => d.events.length === 0 && d.jobs.length === 0}
      emptyTitle="还没有检测任务"
      emptyHint="先建一个数据源与指标，再创建任务"
    >
      {(d) => (
        <section className="panel" aria-labelledby="listTitle">
          <div className="panel__head">
            <div>
              <h2 className="panel__title" id="listTitle">
                告警事件
              </h2>
              <p className="panel__meta mono">
                {d.events.length} 条
                {d.events.length > 0 ? ` · 覆盖 ${d.events.reduce((a, e) => a + e.n_points, 0)} 个告警点` : ''}
              </p>
            </div>
          </div>

          <div className="alert-list__toolbar">
            <Space wrap>
              <Select
                allowClear
                placeholder="全部任务"
                style={{ width: 180 }}
                value={filters.jobId}
                onChange={(value) => onFiltersChange({ ...filters, jobId: value })}
                options={d.jobs.map((job) => ({ value: job.id, label: job.name }))}
              />
              <Select
                allowClear
                placeholder="全部等级"
                style={{ width: 130 }}
                value={filters.level}
                onChange={(value) => onFiltersChange({ ...filters, level: value })}
                options={d.levels.map((level) => ({ value: level, label: level }))}
              />
              <Select
                allowClear
                showSearch
                placeholder="全部序列"
                style={{ width: 220 }}
                value={filters.seriesId}
                onChange={(value) => onFiltersChange({ ...filters, seriesId: value })}
                options={d.series.map((series) => ({ value: series, label: series }))}
              />
              <DatePicker.RangePicker
                showTime
                placeholder={['开始时间', '结束时间']}
                onChange={(range) => {
                  const [from, to] = range ?? []
                  onFiltersChange({
                    ...filters,
                    since: from ? from.toISOString() : undefined,
                    until: to ? to.toISOString() : undefined,
                  })
                }}
              />
              {hasFilters ? (
                <Button
                  size="small"
                  onClick={() =>
                    onFiltersChange({
                      jobId: undefined,
                      level: undefined,
                      seriesId: undefined,
                      since: undefined,
                      until: undefined,
                    })
                  }
                >
                  重置
                </Button>
              ) : null}
            </Space>
          </div>

          {d.events.length === 0 ? (
            <Alert
              className="alert-list__notice"
              type="success"
              showIcon
              message="当前没有告警"
              description="所有任务在最近一次运行里都没有触发告警条件"
            />
          ) : null}
          {d.skipped.length > 0 ? (
            <Alert
              className="alert-list__notice"
              type="warning"
              showIcon
              message={`${d.skipped.length} 个任务未纳入统计`}
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {d.skipped.map((item) => (
                    <li key={item.job_id}>
                      {item.name}：{item.reason}
                    </li>
                  ))}
                </ul>
              }
            />
          ) : null}

          <Table<AlertEvent>
            rowKey={(row) => `${row.job_id}-${row.series_id}-${row.start_ts}`}
            columns={columns}
            dataSource={d.events}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: true }}
            scroll={{ x: 'max-content' }}
          />

          <div className="tfoot">
            <span>
              共 <b>{d.events.length}</b> 条告警事件
            </span>
            <span>
              覆盖 <b>{d.events.reduce((a, e) => a + e.n_points, 0)}</b> 个告警点
            </span>
            <span>
              P0 <b>{d.events.filter((e) => e.level_index >= 2).length}</b> 条
            </span>
            <span>
              P1 <b>{d.events.filter((e) => e.level_index < 2).length}</b> 条
            </span>
          </div>

          <AlertDetailDrawer event={detail} onClose={() => setDetail(null)} />
        </section>
      )}
    </StateBoundary>
  )
}
