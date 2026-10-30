import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, Descriptions, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { StateBoundary } from '../components/StateBoundary'
import { MetricForm } from '../features/metrics/MetricForm'
import { DeleteButton } from '../features/delete/DeleteButton'
import { useCatalog } from '../features/jobs/queries'
import { useDeleteMetric } from '../features/delete/queries'
import type { CatalogMetric } from '../api/types'

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

      <MetricForm
        open={formOpen}
        sources={catalog.data?.sources ?? []}
        editing={editing}
        onCancel={() => {
          setFormOpen(false)
          setEditing(null)
        }}
      />
    </div>
  )
}
