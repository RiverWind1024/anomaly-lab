import { useMemo, useState } from 'react'
import { Button, Drawer, Popconfirm, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtMetric } from '../../lib/format'
import { aggregateBy } from './aggregate'
import { FilterBar } from './FilterBar'
import { DIMENSIONS, filterRows, type DimensionKey, type EvaluationFilters } from './filters'
import { useExcludeEvaluationRow, useRestoreEvaluationRow, useSummary } from './queries'
import { metricClassLabel } from '../jobs/ClassificationCard'
import type { EvaluationRow, Exclusion, Summary as SummaryType } from '../../api/types'

export interface EvaluationTableProps {
  isLoading: boolean
  error: unknown
  summary: SummaryType | undefined
  /** 已排除的记录 —— 详情抽屉里可以恢复。 */
  excludedCount: number
  onOpenExcluded: () => void
  onExclude: (row: EvaluationRow) => void
}

/**
 * 评估总表。
 *
 * 列（照搬旧 `report.js` 的 9 列，**一列都不能少**）：
 * 序列 / 形态 / 检测器 / Precision / Recall / F1 / Range-F1 / 真值点 / 预测点
 */
export function EvaluationTable({
  isLoading,
  error,
  summary,
  excludedCount,
  onOpenExcluded,
  onExclude,
}: EvaluationTableProps) {
  const [filters, setFilters] = useState<EvaluationFilters>({})
  const [dimension, setDimension] = useState<DimensionKey>('metric_class')

  const rows = summary?.rows ?? []
  const filtered = useMemo(() => filterRows(rows, filters), [rows, filters])
  const buckets = useMemo(() => aggregateBy(filtered, dimension), [filtered, dimension])
  const overall = summary?.summary?.overall

  const columns: ColumnsType<EvaluationRow> = useMemo(
    () => [
      {
        title: '序列',
        dataIndex: 'series_id',
        key: 'series_id',
        render: (value: string, row: EvaluationRow) => (
          // 点行看这条序列的检测记录（旧版是点行弹图，新版是独立路由）
          // ⚠️ **带上 detector** —— 记录是「序列 × 算法」，
          //    只带序列的话详情端点只能按默认算法（iqr）去猜。
          <Link
            to={`/detections?series_id=${encodeURIComponent(value)}&detector=${encodeURIComponent(row.detector)}`}
          >
            {value}
          </Link>
        ),
      },
      {
        title: '形态',
        dataIndex: 'metric_class',
        key: 'metric_class',
        width: 170,
        render: (value: string) => (
          // ⚠️ 必须上下两行，不能并排 —— 中文标签 + 原始类名并排的话，
          //    在窄列里会折成竖排（一个字一行），整张表就毁了
          <div className="evaluation__metric-class">
            <span>{metricClassLabel(value)}</span>
            <span className="muted mono">{value}</span>
          </div>
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
      {
        title: '操作',
        key: 'actions',
        width: 110,
        // ⚠️ 固定在右侧 —— 列多的时候横向滚动，
        //    否则「删除」按钮会被推出屏幕外，用户根本找不到
        fixed: 'right',
        render: (_value, row) => (
          <Popconfirm
            title="排除这条检测记录？"
            description="它会从报告里移除，可以在「已排除记录」里恢复。"
            okText="排除"
            cancelText="取消"
            onConfirm={() => onExclude(row)}
          >
            <Button size="small">删除</Button>
          </Popconfirm>
        ),
      },
    ],
    [onExclude],
  )

  const bucketColumns: ColumnsType<(typeof buckets)[number]> = [
    { title: '分组', dataIndex: 'key', key: 'key', width: 200 },
    {
      title: '序列数',
      dataIndex: 'n_series',
      key: 'n_series',
      width: 100,
      align: 'right',
    },
    {
      title: 'Precision',
      dataIndex: 'precision',
      key: 'precision',
      width: 110,
      align: 'right',
      render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: 'Recall',
      dataIndex: 'recall',
      key: 'recall',
      width: 110,
      align: 'right',
      render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: 'F1',
      dataIndex: 'f1',
      key: 'f1',
      width: 100,
      align: 'right',
      render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: 'Range-F1',
      dataIndex: 'range_f1',
      key: 'range_f1',
      width: 120,
      align: 'right',
      render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: '真值点',
      dataIndex: 'n_truth',
      key: 'n_truth',
      width: 100,
      align: 'right',
    },
    {
      title: '预测点',
      dataIndex: 'n_pred',
      key: 'n_pred',
      width: 100,
      align: 'right',
    },
  ]

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
          <div className="filter-bar">
            <FilterBar rows={rows} filters={filters} onChange={setFilters} />
            <Button size="small" onClick={onOpenExcluded}>
              已排除记录{excludedCount > 0 ? `（${excludedCount}）` : ''}
            </Button>
          </div>

          <div className="evaluation__meta muted">
            筛选后 {filtered.length} / {data.rows.length} 条记录
          </div>

          <section className="evaluation__aggregate">
            <div className="evaluation__aggregate-head">
              <h2 className="section__title">聚合统计</h2>
              <Select
                value={dimension}
                style={{ width: 160 }}
                onChange={setDimension}
                options={DIMENSIONS.map((item) => ({ value: item.key, label: `按${item.label}` }))}
              />
            </div>
            <Table<(typeof buckets)[number]>
              rowKey="key"
              columns={bucketColumns}
              dataSource={buckets}
              size="small"
              pagination={false}
              scroll={{ x: 'max-content' }}
            />
          </section>

          <div className="evaluation__detail">
            <Table<EvaluationRow>
              rowKey={(row) => `${row.series_id}-${row.detector}`}
              columns={columns}
              dataSource={filtered}
              size="middle"
              pagination={{ pageSize: 20, showSizeChanger: true }}
              scroll={{ x: 'max-content' }}
            />
          </div>
        </div>
      )}
    </StateBoundary>
  )
}

/** 评估报告页。路由级组件 —— 取数 + 传参。 */
export function EvaluationPage() {
  const summary = useSummary()
  const exclude = useExcludeEvaluationRow()
  const restore = useRestoreEvaluationRow()
  const [excludedOpen, setExcludedOpen] = useState(false)

  const excluded: Exclusion[] = summary.data?.excluded ?? []

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
        excludedCount={excluded.length}
        onOpenExcluded={() => setExcludedOpen(true)}
        onExclude={(row) => exclude.mutate({ series_id: row.series_id, detector: row.detector })}
      />

      <Drawer
        open={excludedOpen}
        onClose={() => setExcludedOpen(false)}
        title="已排除的检测记录"
        width={520}
      >
        {excluded.length === 0 ? (
          <p className="muted">还没有排除任何记录。</p>
        ) : (
          <ul className="excluded-list">
            {excluded.map((item) => (
              <li key={item.key}>
                <Space size="small" wrap>
                  <span className="mono">{item.series_id}</span>
                  <Tag>{item.detector}</Tag>
                  <Button
                    size="small"
                    loading={restore.isPending}
                    onClick={() =>
                      restore.mutate({
                        series_id: item.series_id,
                        detector: item.detector,
                      })
                    }
                  >
                    恢复
                  </Button>
                </Space>
              </li>
            ))}
          </ul>
        )}
      </Drawer>
    </div>
  )
}
