import { useMemo } from 'react'
import { Button, Space, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { DeleteButton } from '../delete/DeleteButton'
import type { Catalog, CatalogJob, OverviewJob } from '../../api/types'
import { formatRules } from './rules'
import { parseTs } from '../../lib/format'

export interface JobListProps {
  isLoading: boolean
  error: unknown
  catalog: Catalog | undefined
  /** 概览里的任务状态 —— 表下摘要要它的「上次跑了多少序列、多少告警点」。 */
  overviewJobs: OverviewJob[]
  runningJobId: number | null
  togglingJobId: number | null
  onRun: (jobId: number) => void
  onToggle: (jobId: number, enabled: boolean) => void
  onCreate: () => void
  onDelete: (jobId: number) => void
  deletingId: number | null
}

/** 下次运行 —— 相对现在说，别只给一个裸时间戳。 */
function nextRunLabel(nextRunAt: string | null): string {
  if (!nextRunAt) return '—'
  const diff = parseTs(nextRunAt) - Date.now()
  if (Number.isNaN(diff)) return '—'
  const minutes = Math.round(diff / 60000)
  if (minutes <= 0) return '即将'
  if (minutes < 60) return `${minutes} 分钟后`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} 小时后`
  return `${Math.round(hours / 24)} 天后`
}

export function JobList({
  isLoading,
  error,
  catalog,
  overviewJobs,
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
      align: 'right',
      render: (value: number) => <span className="mono dim">{value}</span>,
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
        <span className="mono dim">{metricNameById.get(value) ?? String(value)}</span>
      ),
    },
    {
      title: '算法',
      dataIndex: 'detector',
      key: 'detector',
      width: 130,
      render: (value: string) =>
        value === 'auto' ? (
          <span className="pill pill--auto">自动推荐</span>
        ) : (
          <span className="mono dim">{value}</span>
        ),
    },
    {
      title: '告警规则',
      dataIndex: 'alert_rules',
      key: 'alert_rules',
      width: 220,
      render: (value: CatalogJob['alert_rules']) => (
        <Tooltip title={formatRules(value)}>
          <span className="mono dim rules">{formatRules(value)}</span>
        </Tooltip>
      ),
    },
    {
      title: '间隔',
      dataIndex: 'interval_seconds',
      key: 'interval_seconds',
      width: 90,
      align: 'right',
      render: (value: number) => <span className="mono dim">{value}s</span>,
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 90,
      render: (value: boolean) => (
        <span className={`pill ${value ? 'pill--ok' : 'pill--p1'}`}>
          {value ? '启用' : '停用'}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 300,
      // ⚠️ 固定在右侧 —— 三个按钮 + 横向滚动，不固定的话「删除」会被推出屏幕外
      fixed: 'right',
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
      emptyTitle="还没有告警任务"
      emptyHint="先建一个数据源与指标，再创建任务"
      emptyAction={
        <Button type="primary" onClick={onCreate}>
          新建任务
        </Button>
      }
    >
      {(data) => (
        <section className="panel" aria-labelledby="jobsTitle">
          <div className="panel__head">
            <div>
              <h2 className="panel__title" id="jobsTitle">
                任务
              </h2>
              <p className="panel__meta mono">
                {data.jobs.length} 个任务 · {data.jobs.filter((j) => j.enabled).length} 个启用
              </p>
            </div>
          </div>

          <Table<CatalogJob>
            rowKey="id"
            columns={columns}
            dataSource={data.jobs}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: true }}
            scroll={{ x: 'max-content' }}
          />

          {/* 表下一行摘要 —— 每个任务上次跑到哪、下次什么时候 */}
          <div className="tfoot">
            {data.jobs.map((job) => {
              const state = overviewJobs.find((j) => j.id === job.id)
              const last = state?.last_run
              return (
                <span key={job.id}>
                  <b>{job.name}</b>
                  {last ? (
                    <>
                      {' '}
                      上次 #<b>{last.id}</b> · <b>{last.n_series}</b> 条序列 ·{' '}
                      <b>{last.n_alerts}</b> 个告警点
                    </>
                  ) : (
                    ' 还没运行过'
                  )}{' '}
                  · 下次 {nextRunLabel(job.next_run_at)}
                </span>
              )
            })}
          </div>
        </section>
      )}
    </StateBoundary>
  )
}
