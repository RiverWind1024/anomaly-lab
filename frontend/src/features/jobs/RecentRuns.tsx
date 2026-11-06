import { useMemo, useState } from 'react'
import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { useRuns } from './queries'
import type { CatalogJob, RunSummary } from '../../api/types'
import { fmtDateTime } from '../../lib/format'

/**
 * 最近运行 —— 任务跑了什么、跑了多久、报了什么。
 *
 * ⚠️ 一次只查**一个**任务的运行记录（切换任务时才换）——
 *    每个任务都查一遍是 N+1 请求，列表页扛不住。
 */
export function RecentRuns({
  jobs,
  defaultJobId,
}: {
  jobs: CatalogJob[]
  defaultJobId: number | undefined
}) {
  const [jobId, setJobId] = useState<number | undefined>(defaultJobId)
  const runs = useRuns(jobId ?? 0, jobId != null)

  const rows = useMemo(() => runs.data?.runs ?? [], [runs.data])

  const columns: ColumnsType<RunSummary> = [
    {
      title: '运行',
      dataIndex: 'id',
      key: 'id',
      width: 90,
      align: 'right',
      render: (value: number) => <span className="mono">#{value}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (value: string) => (
        <span className={`pill ${value === 'success' ? 'pill--ok' : 'pill--p0'}`}>
          {value === 'success' ? '成功' : '失败'}
        </span>
      ),
    },
    {
      title: '开始',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 140,
      render: (value: string) => <span className="mono dim">{fmtDateTime(value)}</span>,
    },
    {
      title: '耗时',
      key: 'duration',
      width: 90,
      align: 'right',
      render: (_value, row) => (
        <span className="mono dim">{fmtDuration(row.started_at, row.finished_at)}</span>
      ),
    },
    {
      title: '序列',
      dataIndex: 'n_series',
      key: 'n_series',
      width: 80,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '告警',
      dataIndex: 'n_alerts',
      key: 'n_alerts',
      width: 80,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '错误',
      dataIndex: 'error',
      key: 'error',
      render: (value: string | null) => (
        <span className="dim mono">{value ? value.slice(0, 60) : '—'}</span>
      ),
    },
  ]

  const current = jobs.find((j) => j.id === jobId)

  return (
    <section className="panel" aria-labelledby="runsTitle">
      <div className="panel__head">
        <div>
          <h2 className="panel__title" id="runsTitle">
            最近运行
          </h2>
          <p className="panel__meta mono">
            {current ? `${current.name} · ` : ''}
            {rows.length} 次运行
          </p>
        </div>
        {current ? (
          <Link className="link" to={`/jobs/${current.id}/runs`}>
            打开任务详情
          </Link>
        ) : null}
      </div>

      {/* 切任务 —— 一次只查一个，不做 N+1 */}
      <div className="seg" role="tablist" aria-label="按任务筛选运行记录">
        {jobs.map((job) => (
          <button
            key={job.id}
            type="button"
            role="tab"
            aria-selected={job.id === jobId}
            onClick={() => setJobId(job.id)}
          >
            {job.name}
          </button>
        ))}
      </div>

      <Table<RunSummary>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        size="middle"
        pagination={{ pageSize: 8, hideOnSinglePage: true }}
        scroll={{ x: 'max-content' }}
        style={{ marginTop: 12 }}
      />
    </section>
  )
}

/** 运行时长。 */
function fmtDuration(startedAt: string, finishedAt: string | null): string {
  if (!finishedAt) return '—'
  const start = Date.parse(startedAt)
  const end = Date.parse(finishedAt)
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m${seconds % 60 ? ` ${seconds % 60}s` : ''}`
}
