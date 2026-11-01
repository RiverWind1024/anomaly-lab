import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, Descriptions, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { StateBoundary } from '../components/StateBoundary'
import { MetricForm } from '../features/metrics/MetricForm'
import { DeleteButton } from '../features/delete/DeleteButton'
import { DataBrowser } from '../features/sources/DataBrowser'
import { useCatalog } from '../features/jobs/queries'
import { useDeleteMetric } from '../features/delete/queries'
import type { CatalogMetric, SourceQueryColumn } from '../api/types'

/**
 * 数据源详情页 —— **指标的父级**。
 *
 * 层级是 数据源 → 指标 → 序列：
 * 这里列的是「这个数据源下配了哪些指标」，点指标进指标详情。
 */
export function SourceDetailPage() {
  const params = useParams<{ sourceId: string }>()
  const sourceId = Number(params.sourceId ?? 0)
  const catalog = useCatalog()
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<CatalogMetric | null>(null)
  /** 浏览器里查出来的结果 —— 用来给指标表单预填。 */
  const [browserResult, setBrowserResult] = useState<{
    sql: string
    columns: SourceQueryColumn[]
    time_column?: string
    value_column?: string
    time_format?: string
  } | null>(null)
  const deleteMetric = useDeleteMetric()

  const source = catalog.data?.sources.find((item) => item.id === sourceId)
  const metrics = (catalog.data?.metrics ?? []).filter((item) => item.source_id === sourceId)

  const columns: ColumnsType<CatalogMetric> = [
    {
      title: '指标',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, row) => <Link to={`/metrics/${row.id}`}>{value}</Link>,
    },
    {
      title: '分组列',
      dataIndex: 'group_column',
      key: 'group_column',
      width: 140,
      render: (value: string | null) =>
        value ? <span className="mono">{value}</span> : <span className="muted">—</span>,
    },
    {
      title: '频率',
      dataIndex: 'freq',
      key: 'freq',
      width: 100,
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '时间格式',
      dataIndex: 'time_format',
      key: 'time_format',
      width: 130,
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_value, row) => (
        <Space size="small">
          <Button
            size="small"
            onClick={() => {
              setEditing(row)
              setFormOpen(true)
            }}
          >
            编辑
          </Button>
          {/* ⚠️ 删除必须走 DeleteButton —— 它带**影响预览**与二次确认。
              裸按钮误点就没了，而删指标会连带删掉任务与运行记录。 */}
          <DeleteButton
            target="metric"
            id={row.id}
            name={row.name}
            catalog={catalog.data}
            loading={deleteMetric.isPending && deleteMetric.variables === row.id}
            onConfirm={() => deleteMetric.mutate(row.id)}
          />
        </Space>
      ),
    },
  ]

  /**
   * 「用这个结果建指标」—— 把浏览到的列名带进指标表单。
   *
   * ⚠️ 时间列只能从 TIMESTAMP 列里猜、值列从数值列里猜 ——
   *    猜不到就留空，让用户自己填（留个错的默认值更糟）。
   */
  const handleUseAsMetric = (payload: { sql: string; columns: SourceQueryColumn[] }) => {
    const time = payload.columns.find((c) => c.type === 'TIMESTAMP')
    const numeric = payload.columns.find((c) => c.type === 'REAL' || c.type === 'INTEGER')
    setBrowserResult({
      sql: payload.sql,
      columns: payload.columns,
      time_column: time?.name,
      value_column: numeric?.name,
      time_format: time ? 'iso_utc' : undefined,
    })
    setEditing(null)
    setFormOpen(true)
  }

  if (catalog.data && !source) {
    return (
      <div className="page">
        <header className="page__header">
          <h1 className="page__title">数据源</h1>
        </header>
        <div className="empty-state">
          <p className="empty-state__title">数据源不存在或已被删除</p>
          <Link to="/sources">← 回到数据源列表</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">{source?.name ?? '数据源'}</h1>
        <p className="page__subtitle">
          <Link to="/sources">数据源</Link> / {source?.name ?? sourceId}
        </p>
      </header>

      <Descriptions size="small" column={3} bordered className="source-detail__info">
        <Descriptions.Item label="类型">
          <Tag>{source?.kind ?? '—'}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="路径">
          <span className="mono">{source?.path ?? '—'}</span>
        </Descriptions.Item>
        <Descriptions.Item label="创建时间">
          <span className="mono">{source?.created_at?.slice(0, 19).replace('T', ' ') ?? '—'}</span>
        </Descriptions.Item>
      </Descriptions>

      <div className="source-detail__toolbar">
        <span className="muted">共 {metrics.length} 个指标</span>
        <Button type="primary" onClick={() => setFormOpen(true)}>
          新增指标
        </Button>
      </div>

      <StateBoundary
        isLoading={catalog.isPending}
        error={catalog.error}
        data={metrics}
        isEmpty={(data) => data.length === 0}
        emptyTitle="这个数据源还没有指标"
        emptyHint="指标定义「从哪个数据源、取哪些列、怎么算频率」—— 没有指标就没法建检测任务"
      >
        {(data) => (
          <Table<CatalogMetric>
            rowKey="id"
            columns={columns}
            dataSource={data}
            size="middle"
            pagination={false}
            scroll={{ x: 'max-content' }}
          />
        )}
      </StateBoundary>

      <DataBrowser sourceId={sourceId} onUseAsMetric={handleUseAsMetric} />

      <MetricForm
        open={formOpen}
        sources={catalog.data?.sources ?? []}
        editing={editing}
        // ⚠️ 不给默认数据源的话，从浏览器建的指标「数据源」是空的
        defaultSourceId={sourceId}
        initialValues={
          browserResult
            ? {
                // ⚠️ 只有 SQL 里带 $timefilter 才预填 query ——
                //    指标要求恰好一个 $timefilter，预填非法 SQL 会让用户白填一遍
                ...(browserResult.sql.includes('$timefilter')
                  ? { query: browserResult.sql }
                  : {}),
                time_column: browserResult.time_column ?? '',
                value_column: browserResult.value_column ?? '',
                time_format: browserResult.time_format ?? 'iso_utc',
              }
            : undefined
        }
        onCancel={() => {
          setFormOpen(false)
          setEditing(null)
          // ⚠️ 清掉浏览结果 —— 否则下次打开还带着上次的预填
          setBrowserResult(null)
        }}
      />
    </div>
  )
}
