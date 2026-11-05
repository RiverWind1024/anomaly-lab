import { Button, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { detectorLabel } from '../../lib/detectorLabels'
import type { LabExperimentSummary } from '../../api/types'

/**
 * 已保存的实验记录。
 *
 * ⚠️ 这一块的作用是**可复现**：记录里存着 spec + 环境 + 结果 + 指纹，
 *    将来能拿着它重跑一遍，看结论是否还成立。
 */

export interface ExperimentRecordsProps {
  records: LabExperimentSummary[]
  loading?: boolean
  /** 点「一键建任务」—— 把记录 id 交回去，由页面跳转。 */
  onCreateJob: (recordId: string) => void
  /** 正在为哪条记录建任务（用来禁用按钮）。 */
  creatingJobId?: string | null
  /** 记录为空时显示的提示。 */
  emptyHint?: string
}

export function ExperimentRecords({
  records,
  loading = false,
  onCreateJob,
  creatingJobId = null,
  emptyHint,
}: ExperimentRecordsProps) {
  const columns: ColumnsType<LabExperimentSummary> = [
    {
      title: '时间（UTC）',
      dataIndex: 'created_at',
      width: 170,
      render: (value: string) => (
        <span className="mono">{dayjs(value).format('MM-DD HH:mm:ss')}</span>
      ),
    },
    {
      title: '指标',
      key: 'metric',
      render: (_, row) => (
        <span>
          {row.spec.metric_name ?? `指标 ${row.spec.metric_id ?? '—'}`}
          <span className="muted mono"> · {row.spec.freq ?? '—'}</span>
        </span>
      ),
    },
    {
      title: '窗口',
      key: 'window',
      align: 'right',
      render: (_, row) => (
        <span className="mono">
          {row.spec.sampling?.window_points ?? '—'} 点 × {row.summary.n_windows} 窗
        </span>
      ),
    },
    {
      title: '检出画像',
      key: 'detectors',
      render: (_, row) => (
        <span className="muted">
          {row.summary.detectors
            .map((item) => `${detectorLabel(item.detector)} ${item.n_alerts ?? 0}`)
            .join(' · ') || '—'}
        </span>
      ),
    },
    {
      title: '指纹',
      key: 'fingerprint',
      width: 110,
      render: (_, row) => (
        <Tooltip title={`结果指纹：${row.fingerprint}（剔除耗时后的内容哈希）`}>
          <span className="mono muted">{row.fingerprint.slice(7, 19)}</span>
        </Tooltip>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 110,
      align: 'right',
      render: (_, row) => (
        <Button
          size="small"
          loading={creatingJobId === row.id}
          disabled={row.spec.kind !== 'metric'}
          data-testid="lab-create-job"
          title={
            row.spec.kind !== 'metric'
              ? '临时 SQL 的实验无法直接建任务 —— 请先把 SQL 固化成指标'
              : undefined
          }
          onClick={() => onCreateJob(row.id)}
        >
          一键建任务
        </Button>
      ),
    },
  ]

  return (
    <Table<LabExperimentSummary>
      size="small"
      rowKey="id"
      columns={columns}
      dataSource={records}
      loading={loading}
      pagination={false}
      scroll={{ x: 900 }}
      locale={{ emptyText: emptyHint ?? '还没有保存过实验记录' }}
    />
  )
}
