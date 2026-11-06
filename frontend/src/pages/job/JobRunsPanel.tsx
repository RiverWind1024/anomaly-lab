import { Button, message, Table, Tag } from 'antd'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { useRuns, useRunJob } from '../../features/jobs/queries'
import type { RunSummary } from '../../api/types'
import { fmtFullDateTime } from '../../lib/format'

export interface JobRunsPanelProps {
  jobId: number
  enabled: boolean
}

/** 运行状态的中文名（后端存的是英文）。 */
const RUN_STATUS_LABEL: Record<string, string> = {
  success: '成功',
  failed: '失败',
  running: '运行中',
  pending: '排队中',
}

function fmtTime(value: string | null): string {
  return fmtFullDateTime(value)
}

/** 运行时长（秒）。 */
function fmtDuration(startedAt: string, finishedAt: string | null): string {
  if (!finishedAt) return '—'
  const start = Date.parse(startedAt)
  const end = Date.parse(finishedAt)
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

/**
 * 运行记录面板。
 *
 * 之前运行记录只是一个下拉框，藏在详情页最上面 ——
 * 现在独立成页，能看到每次运行的序列数、告警数、耗时、错误。
 */
export function JobRunsPanel({ jobId, enabled }: JobRunsPanelProps) {
  const navigate = useNavigate()
  const runs = useRuns(jobId, enabled)
  const runJob = useRunJob()

  const handleRun = () => {
    runJob.mutate(jobId, {
      onSuccess: () => message.success(`任务 ${jobId} 已触发立即运行`),
      onError: (err) => message.error(err instanceof Error ? err.message : '运行失败'),
    })
  }

  const columns: ColumnsType<RunSummary> = [
    { title: '运行', dataIndex: 'id', key: 'id', width: 80, render: (v: number) => `#${v}` },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (value: string) => (
        <Tag
          color={
            value === 'success' ? 'success' : value === 'running' ? 'processing' : 'error'
          }
        >
          {RUN_STATUS_LABEL[value] ?? value}
        </Tag>
      ),
    },
    {
      title: '检测序列',
      dataIndex: 'n_series',
      key: 'n_series',
      width: 100,
      align: 'right',
    },
    {
      title: '告警数',
      dataIndex: 'n_alerts',
      key: 'n_alerts',
      width: 90,
      align: 'right',
    },
    { title: '开始时间', dataIndex: 'started_at', key: 'started_at', width: 200, render: fmtTime },
    {
      title: '耗时',
      key: 'duration',
      width: 140,
      render: (_v, row) => fmtDuration(row.started_at, row.finished_at),
    },
    {
      title: '错误',
      dataIndex: 'error',
      key: 'error',
      render: (value: string | null) =>
        value ? <span className="muted">{value}</span> : <span className="muted">—</span>,
    },
    {
      title: '',
      key: 'open',
      width: 110,
      render: () => <span className="mono dim">查看流程 →</span>,
    },
  ]

  return (
    <div className="job-runs">
      <div className="job-runs__toolbar">
        <span className="muted">
          共 {runs.data?.runs.length ?? 0} 次运行 · 点任意一行看那次运行的检测流程
        </span>
        <Button type="primary" loading={runJob.isPending} onClick={handleRun}>
          立即运行
        </Button>
      </div>

      <Table<RunSummary>
        rowKey="id"
        columns={columns}
        dataSource={runs.data?.runs ?? []}
        size="middle"
        loading={runs.isPending}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        onRow={(row) => ({
          // ⚠️ 点进「检测结果」并**带上 run_id** —— 不带的话那个页面永远只显示最近一次，
          //    用户会以为历史运行没有检测记录。
          onClick: () => navigate(`/jobs/${jobId}/detections?run_id=${row.id}`),
          style: { cursor: 'pointer' },
        })}
        scroll={{ x: 'max-content' }}
      />
    </div>
  )
}
