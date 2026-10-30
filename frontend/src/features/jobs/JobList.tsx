import { useMemo } from 'react'
import { Button, Space, Table, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { DeleteButton } from '../delete/DeleteButton'
import type { Catalog, CatalogJob } from '../../api/types'
import { formatRules } from './rules'

export interface JobListProps {
  isLoading: boolean
  error: unknown
  catalog: Catalog | undefined
  runningJobId: number | null
  togglingJobId: number | null
  onRun: (jobId: number) => void
  onToggle: (jobId: number, enabled: boolean) => void
  onCreate: () => void
  onDelete: (jobId: number) => void
  deletingId: number | null
}

export function JobList({
  isLoading,
  error,
  catalog,
  runningJobId,
  togglingJobId,
  onRun,
  onToggle,
  onCreate,
  onDelete,
  deletingId,
}: JobListProps) {
  const metricNameById = useMemo(
    () => new Map((catalog?.metrics ?? []).map((m) => [m.id, m.name])),
    [catalog?.metrics],
  )

  const columns: ColumnsType<CatalogJob> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 70,
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, row) => <Link to={`/jobs/${row.id}`}>{value}</Link>,
    },
    {
      title: '指标',
      dataIndex: 'metric_id',
      key: 'metric_id',
      width: 160,
      render: (value: number) => (
        <span className="mono">{metricNameById.get(value) ?? String(value)}</span>
      ),
    },
    {
      title: '算法',
      dataIndex: 'detector',
      key: 'detector',
      width: 130,
      render: (value: string) => (
        value === 'auto' ? <Tag color="processing">自动推荐</Tag> : <span className="mono">{value}</span>
      ),
    },
    {
      title: '告警规则',
      dataIndex: 'alert_rules',
      key: 'alert_rules',
      width: 220,
      render: (value: CatalogJob['alert_rules']) => (
        <Tooltip title={formatRules(value)}>
          <span className="mono job-list__rules">{formatRules(value)}</span>
        </Tooltip>
      ),
    },
    {
      title: '间隔',
      dataIndex: 'interval_seconds',
      key: 'interval_seconds',
      width: 90,
      align: 'right',
      render: (value: number) => <span className="mono">{value}s</span>,
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 90,
      render: (value: boolean) => (
        <Tag color={value ? 'success' : 'default'}>{value ? '启用' : '停用'}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_value, row) => (
        <Space size="small">
          <Button
            size="small"
            type="primary"
            loading={runningJobId === row.id}
            onClick={() => onRun(row.id)}
          >
            立即运行
          </Button>
          <Button
            size="small"
            loading={togglingJobId === row.id}
            onClick={() => onToggle(row.id, !row.enabled)}
          >
            {row.enabled ? '停用' : '启用'}
          </Button>
          <DeleteButton
            target="job"
            id={row.id}
            name={row.name}
            catalog={catalog}
            loading={deletingId === row.id}
            onConfirm={() => onDelete(row.id)}
          />
        </Space>
      ),
    },
  ]

  return (
    <StateBoundary
      isLoading={isLoading}
      error={error}
      data={catalog}
      isEmpty={(data) => data.jobs.length === 0}
      emptyTitle="还没有检测任务"
      emptyHint="先建一个数据源与指标，再创建任务"
      emptyAction={
        <Button type="primary" onClick={onCreate}>
          新建任务
        </Button>
      }
    >
      {(data) => (
        <>
          <div className="job-list__toolbar">
            <span className="muted">共 {data.jobs.length} 个任务</span>
            <Button type="primary" onClick={onCreate}>
              新建任务
            </Button>
          </div>
          <Table<CatalogJob>
            rowKey="id"
            columns={columns}
            dataSource={data.jobs}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: true }}
            scroll={{ x: 'max-content' }}
          />
        </>
      )}
    </StateBoundary>
  )
}
