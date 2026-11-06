import { useMemo, useState } from 'react'
import { Button, Drawer, Popconfirm, Space, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link, useSearchParams } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtMetric, fmtDateTime } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import './evaluation.css'
import { aggregateBy } from './aggregate'
import { FilterBar } from './FilterBar'
import { ProductionEvaluationPanel } from './ProductionEvaluationPanel'
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
  // 最好 / 最差形态：与结论句同源（都取整份报告，不随筛选变化）
  const ranked = Object.entries(summary?.summary.by_metric_class ?? {}).sort(
    (a, b) => b[1].f1 - a[1].f1,
  )
  const best = ranked[0]
  const worst = ranked[ranked.length - 1]

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
        width: 160,
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
        width: 96,
        render: (value: string) => <span className="mono">{value}</span>,
      },
      {
        title: 'Precision',
        dataIndex: 'precision',
        key: 'precision',
        width: 92,
        align: 'right',
        render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
      },
      {
        title: 'Recall',
        dataIndex: 'recall',
        key: 'recall',
        width: 92,
        align: 'right',
        render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
      },
      {
        title: 'F1',
        dataIndex: 'f1',
        key: 'f1',
        width: 84,
        align: 'right',
        render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
      },
      {
        title: 'Range-F1',
        dataIndex: 'range_f1',
        key: 'range_f1',
        width: 104,
        align: 'right',
        render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
      },
      {
        title: '真值点',
        dataIndex: 'n_truth',
        key: 'n_truth',
        width: 84,
        align: 'right',
        render: (value: number) => <span className="mono">{value}</span>,
      },
      {
        title: '预测点',
        dataIndex: 'n_pred',
        key: 'n_pred',
        width: 84,
        align: 'right',
        render: (value: number) => <span className="mono">{value}</span>,
      },
      {
        title: '操作',
        key: 'actions',
        width: 96,
        // ⚠️ 固定在右侧 —— 列多的时候横向滚动，
        //    否则「排除」按钮会被推出屏幕外，用户根本找不到
        fixed: 'right',
        render: (_value, row) => (
          <Popconfirm
            title="排除这条检测记录？"
            description="它会从报告里移除，可以在「已排除记录」里恢复。"
            okText="排除"
            cancelText="取消"
            onConfirm={() => onExclude(row)}
          >
            <Button size="small" type="text">
              排除
            </Button>
          </Popconfirm>
        ),
      },
    ],
    [onExclude],
  )

  const dimensionLabel = DIMENSIONS.find((item) => item.key === dimension)?.label ?? ''
  const totals = buckets.reduce(
    (acc, bucket) => ({
      n_series: acc.n_series + bucket.n_series,
      n_truth: acc.n_truth + bucket.n_truth,
      n_pred: acc.n_pred + bucket.n_pred,
    }),
    { n_series: 0, n_truth: 0, n_pred: 0 },
  )

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
            <div className="evaluation__overall evaluation__conclusion">
              <div className="evaluation__metrics">
                <span className="evaluation__metric">
                  <span className="evaluation__metric-k">F1</span>
                  <b className="evaluation__metric-v num">{fmtMetric(overall.f1)}</b>
                </span>
                <span className="evaluation__metric">
                  <span className="evaluation__metric-k">Precision</span>
                  <b className="evaluation__metric-v num">{fmtMetric(overall.precision)}</b>
                </span>
                <span className="evaluation__metric">
                  <span className="evaluation__metric-k">Recall</span>
                  <b className="evaluation__metric-v num">{fmtMetric(overall.recall)}</b>
                </span>
                <span className="evaluation__metric">
                  <span className="evaluation__metric-k">Range-F1</span>
                  <b className="evaluation__metric-v num">{fmtMetric(overall.range_f1)}</b>
                </span>
                <span className="evaluation__metric">
                  <span className="evaluation__metric-k">记录数</span>
                  <b className="evaluation__metric-v num">{data.rows.length.toLocaleString()}</b>
                </span>
              </div>
              {best && worst && best[0] !== worst[0] ? (
                <p className="evaluation__verdict">
                  <b>{metricClassLabel(best[0])}</b> 最好（
                  <span className="num">{fmtMetric(best[1].f1)}</span>）
                  <span className="evaluation__verdict-sep" aria-hidden="true">
                    ·
                  </span>
                  <b>{metricClassLabel(worst[0])}</b> 最差（
                  <span className="num">{fmtMetric(worst[1].f1)}</span>）
                </p>
              ) : null}
            </div>
          )}

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">分组表现</h2>
                <p className="panel__meta">按{dimensionLabel}汇总</p>
              </div>
              <div className="seg" role="tablist" aria-label="聚合维度">
                {DIMENSIONS.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    role="tab"
                    aria-selected={dimension === item.key}
                    onClick={() => setDimension(item.key)}
                  >
                    按{item.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="eval-groups" role="table" aria-label={`按${dimensionLabel}分组的表现`}>
              <div className="eval-groups__row eval-groups__row--head" role="row">
                <span role="columnheader">{dimensionLabel}</span>
                <span role="columnheader">F1</span>
                <span className="eval-groups__r" role="columnheader">
                  Precision
                </span>
                <span className="eval-groups__r" role="columnheader">
                  Recall
                </span>
                <span className="eval-groups__r" role="columnheader">
                  序列
                </span>
              </div>
              {buckets.map((bucket) => {
                const label = metricClassLabel(bucket.key)
                return (
                  <div className="eval-groups__row" role="row" key={bucket.key}>
                    <span className="eval-groups__name" role="cell">
                      <b>{label}</b>
                      {label !== bucket.key ? <span className="mono dim">{bucket.key}</span> : null}
                    </span>
                    <div className="eval-groups__score" role="cell">
                      <span className="num">{fmtMetric(bucket.f1)}</span>
                      <i className="eval-bar" aria-hidden="true">
                        <i style={{ width: `${Math.max(0, Math.min(1, bucket.f1)) * 100}%` }} />
                      </i>
                    </div>
                    <span className="eval-groups__r num" role="cell">
                      {fmtMetric(bucket.precision)}
                    </span>
                    <span className="eval-groups__r num" role="cell">
                      {fmtMetric(bucket.recall)}
                    </span>
                    <span className="eval-groups__r num" role="cell">
                      {bucket.n_series}
                    </span>
                  </div>
                )
              })}
            </div>

            <p className="tfoot">
              <span>
                合计 <b className="num">{totals.n_series}</b> 条序列
              </span>
              <span>
                标注 <b className="num">{totals.n_truth.toLocaleString()}</b> 点
              </span>
              <span>
                预测 <b className="num">{totals.n_pred.toLocaleString()}</b> 点
              </span>
            </p>
          </section>

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">序列明细</h2>
                <p className="panel__meta">点序列名查看该条记录的检测明细</p>
              </div>
              <Button type="text" size="small" onClick={onOpenExcluded}>
                已排除记录{excludedCount > 0 ? `（${excludedCount}）` : ''}
              </Button>
            </div>
            <div className="filter-bar evaluation__filters">
              <FilterBar rows={rows} filters={filters} onChange={setFilters} />
              <span className="filter-bar__count">
                筛选后 <b className="num">{filtered.length}</b> / {data.rows.length} 条记录
              </span>
            </div>
            <div className="evaluation__detail">
              <Table<EvaluationRow>
                rowKey={(row) => `${row.series_id}-${row.detector}`}
                columns={columns}
                dataSource={filtered}
                size="small"
                pagination={{ pageSize: 20, showSizeChanger: true }}
                scroll={{ x: 'max-content' }}
              />
            </div>
          </section>
        </div>
      )}
    </StateBoundary>
  )
}

/** 两个视图的口径完全不同：离线回测（合成集）与生产评估（人工标注）。 */
export type EvaluationTab = 'offline' | 'production'

/** 从 URL 解析当前视图。不带 `tab` 的旧链接一律按「离线回测」处理。 */
export function tabFromParams(params: URLSearchParams): EvaluationTab {
  return params.get('tab') === 'production' ? 'production' : 'offline'
}

const TAB_ITEMS = [
  { key: 'offline', label: '离线回测' },
  { key: 'production', label: '生产评估' },
]

/** 评估报告页。路由级组件 —— 取数 + 传参。 */
export function EvaluationPage() {
  const [params, setParams] = useSearchParams()
  const summary = useSummary()
  const exclude = useExcludeEvaluationRow()
  const restore = useRestoreEvaluationRow()
  const [excludedOpen, setExcludedOpen] = useState(false)

  const tab = tabFromParams(params)
  const excluded: Exclusion[] = summary.data?.excluded ?? []

  /** 切视图写回 URL —— 刷新、分享链接都不丢；离线态不保留多余参数。 */
  const changeTab = (key: string) => {
    const next = new URLSearchParams(params)
    if (key === 'production') next.set('tab', 'production')
    else next.delete('tab')
    setParams(next, { replace: true })
  }

  return (
    <div className="page page--evaluation">
      <header className="page__header">
        <h1 className="page__title">评估报告</h1>
        {/* 一行说清「这份报告是什么 + 什么时候生成的」；高度固定，数据到达前后不跳 */}
        <p className="evaluation__provenance">
          {summary.data ? (
            <>
              {summary.data.title || '回测'}报告 · 生成于{' '}
              <span className="num">{fmtDateTime(summary.data.generated_at)}</span>
            </>
          ) : (
            '加载中…'
          )}
        </p>
      </header>

      <Tabs
        className="evaluation__tabs"
        activeKey={tab}
        items={TAB_ITEMS}
        onChange={changeTab}
      />

      {tab === 'offline' ? (
        <EvaluationTable
          isLoading={summary.isPending}
          error={summary.error}
          summary={summary.data}
          excludedCount={excluded.length}
          onOpenExcluded={() => setExcludedOpen(true)}
          onExclude={(row) => exclude.mutate({ series_id: row.series_id, detector: row.detector })}
        />
      ) : (
        <section className="evaluation__production">
          <p className="evaluation__production-note">
            这一块用的是<b>人工标注 × 线上运行</b>，和「离线回测」的合成集回测不是一套数据。
          </p>
          <ProductionEvaluationPanel />
        </section>
      )}

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
                  <Tag>{detectorLabel(item.detector)}</Tag>
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
