import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { StateBoundary } from '../../components/StateBoundary'
import type { FeedbackRecord } from '../../api/types'
import { FEEDBACK_KIND_LABELS } from './FeedbackPanel'
import { fmtFullDateTime } from '../../lib/format'

export interface FeedbackHistoryProps {
  isLoading: boolean
  error: unknown
  feedback: FeedbackRecord[] | undefined
}

/** 反馈类型 → 颜色。漏报/误报是「有问题」，正确是「没问题」。 */
function kindColor(kind: string): string {
  if (kind === 'missed') return 'error'
  if (kind === 'false_alarm') return 'warning'
  if (kind === 'correct') return 'success'
  return 'default'
}

/**
 * 反馈历史表。
 *
 * 列：ID / 序列 / 时间范围（`start_ts` ~ `end_ts`）/ 类型 / 备注。
 */
export function FeedbackHistory({ isLoading, error, feedback }: FeedbackHistoryProps) {
  const columns: ColumnsType<FeedbackRecord> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 70,
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '序列',
      dataIndex: 'series_id',
      key: 'series_id',
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '时间范围',
      key: 'range',
      render: (_value, row) => (
        <span className="mono nowrap">
          {fmtFullDateTime(row.start_ts)} ~ {fmtFullDateTime(row.end_ts)}
        </span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'kind',
      key: 'kind',
      width: 100,
      render: (value: string) => (
        <Tag color={kindColor(value)}>{FEEDBACK_KIND_LABELS[value as never] ?? value}</Tag>
      ),
    },
    {
      title: '备注',
      dataIndex: 'note',
      key: 'note',
      render: (value: string) => value || <span className="muted">—</span>,
    },
  ]

  return (
    <StateBoundary
      isLoading={isLoading}
      error={error}
      data={feedback}
      isEmpty={(data) => data.length === 0}
      emptyTitle="还没有反馈记录"
      emptyHint="提交一条「漏报」或「误报」，就能用来给出调参建议"
    >
      {(data) => (
        <Table<FeedbackRecord>
          rowKey="id"
          columns={columns}
          dataSource={data}
          size="middle"
          pagination={{ pageSize: 10 }}
          scroll={{ x: 'max-content' }}
        />
      )}
    </StateBoundary>
  )
}
