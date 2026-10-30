import { Alert, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
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
 * 档位越严重颜色越重。
 *
 * ⚠️ 用 `level_index` 而不是档位名 —— 档位名是自定义的（「注意」「P0」），
 *    没法按名字判严重度。
 */
function levelColor(levelIndex: number): string {
  if (levelIndex >= 3) return 'red'
  if (levelIndex === 2) return 'orange'
  return 'gold'
}

function fmtTime(value: string): string {
  return value.replace('T', ' ').slice(0, 16)
}

export function AlertList({ isLoading, error, data, filters, onFiltersChange }: AlertListProps) {
  const columns: ColumnsType<AlertEvent> = [
    {
      title: '等级',
      dataIndex: 'level',
      key: 'level',
      width: 90,
      render: (value: string, row) => (
        <Tag color={levelColor(row.level_index)}>{value}</Tag>
      ),
    },
    {
      title: '时间',
      key: 'time',
      width: 260,
      render: (_value, row) => (
        <span className="mono">
          {fmtTime(row.start_ts)} ~ {fmtTime(row.end_ts)}
        </span>
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
      title: '峰值分数',
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
      render: (value: string) => <span className="mono">{value}</span>,
    },
  ]

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
        <>
          <div className="alert-list__toolbar">
            <Space>
              <Select
                allowClear
                placeholder="全部任务"
                style={{ width: 200 }}
                value={filters.jobId}
                onChange={(value) => onFiltersChange({ ...filters, jobId: value })}
                options={d.jobs.map((job) => ({ value: job.id, label: job.name }))}
              />
              <Select
                allowClear
                placeholder="全部等级"
                style={{ width: 140 }}
                value={filters.level}
                onChange={(value) => onFiltersChange({ ...filters, level: value })}
                options={d.levels.map((level) => ({ value: level, label: level }))}
              />
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
        </>
      )}
    </StateBoundary>
  )
}
