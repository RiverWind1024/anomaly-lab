import { useMemo } from 'react'
import { Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import type { EvaluationRow, Summary } from '../../api/types'
import { metricClassLabel } from '../jobs/ClassificationCard'
import { useSummary } from './queries'

export interface EvaluationTableProps {
  isLoading: boolean
  error: unknown
  summary: Summary | undefined
}

/** 数值格式化：非有限值显示「—」（旧版 report.js 的 fmt）。 */
export function fmtMetric(value: number | null | undefined): string {
  return Number.isFinite(value) ? Number(value).toFixed(3) : '—'
}

/**
 * 评估总表。
 *
 * 列（照搬旧 `report.js` 的 9 列，**一列都不能少**）：
 * 序列 / 形态 / 检测器 / Precision / Recall / F1 / Range-F1 / 真值点 / 预测点
 */
export function EvaluationTable({ isLoading, error, summary }: EvaluationTableProps) {
  const columns: ColumnsType<EvaluationRow> = useMemo(
    () => [
      {
        title: '序列',
        dataIndex: 'series_id',
        key: 'series_id',
        render: (value: string) => (
          // 点行看这条序列的检测记录（旧版是点行弹图，新版是独立路由）
          <Link to={`/detections?series_id=${encodeURIComponent(value)}`}>{value}</Link>
        ),
      },
      {
        title: '形态',
        dataIndex: 'metric_class',
        key: 'metric_class',
        width: 130,
        render: (value: string) => (
          <Space size="small">
            {metricClassLabel(value)}
            <span className="muted mono">{value}</span>
          </Space>
        ),
      },
      {
        title: '检测器',
        dataIndex: 'detector',
        key: 'detector',
        width: 110,
        render: (value: string) => <span className="mono">{value}</span>,
      },
      {
        title: 'Precision',
        dataIndex: 'precision',
        key: 'precision',
        width: 100,
        align: 'right',
        render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
      },
      {
        title: 'Recall',
        dataIndex: 'recall',
        key: 'recall',
        width: 100,
        align: 'right',
        render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
      },
      {
        title: 'F1',
        dataIndex: 'f1',
        key: 'f1',
        width: 90,
        align: 'right',
        render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
      },
      {
        title: 'Range-F1',
        dataIndex: 'range_f1',
        key: 'range_f1',
        width: 110,
        align: 'right',
        render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
      },
      {
        title: '真值点',
        dataIndex: 'n_truth',
        key: 'n_truth',
        width: 90,
        align: 'right',
        render: (value: number) => <span className="mono">{value}</span>,
      },
      {
        title: '预测点',
        dataIndex: 'n_pred',
        key: 'n_pred',
        width: 90,
        align: 'right',
        render: (value: number) => <span className="mono">{value}</span>,
      },
    ],
    [],
  )

  const overall = summary?.summary?.overall

  return (
    <StateBoundary
      isLoading={isLoading}
      error={error}
      data={summary}
      isEmpty={(data) => data.rows.length === 0}
      emptyTitle="暂无报告，请先运行 evaluate"
      emptyHint="在仓库根目录执行 make evaluate 生成回测报告"
    >
      {(data) => (
        <div className="evaluation">
          {overall && (
            <div className="evaluation__overall">
              <Tag>总体</Tag>
              <span>
                Precision <span className="mono">{fmtMetric(overall.precision)}</span>
              </span>
              <span>
                Recall <span className="mono">{fmtMetric(overall.recall)}</span>
              </span>
              <span>
                F1 <span className="mono">{fmtMetric(overall.f1)}</span>
              </span>
              <span>
                Range-F1 <span className="mono">{fmtMetric(overall.range_f1)}</span>
              </span>
              <span className="muted">
                {overall.n_series} 条序列 · 真值 {overall.n_truth} 点 · 预测 {overall.n_pred} 点
              </span>
            </div>
          )}
          <Table<EvaluationRow>
            rowKey="series_id"
            columns={columns}
            dataSource={data.rows}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: true }}
            scroll={{ x: 'max-content' }}
          />
        </div>
      )}
    </StateBoundary>
  )
}

/** 评估报告页。路由级组件 —— 取数 + 传参。 */
export function EvaluationPage() {
  const summary = useSummary()
  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">评估报告</h1>
        <p className="page__subtitle">
          {summary.data ? `${summary.data.rows.length} 条序列的回测结果` : '加载中…'}
        </p>
      </header>

      <EvaluationTable
        isLoading={summary.isPending}
        error={summary.error}
        summary={summary.data}
      />
    </div>
  )
}
