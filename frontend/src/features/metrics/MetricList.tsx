import { Button, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { DeleteButton } from '../delete/DeleteButton'
import type { Catalog, CatalogMetric, CatalogSource } from '../../api/types'

export interface MetricListProps {
  isLoading: boolean
  error: unknown
  metrics: CatalogMetric[] | undefined
  sources: CatalogSource[] | undefined
  /** 删除影响预览要用的全量数据（catalog）。 */
  catalog: Catalog | undefined
  onDelete: (metricId: number) => void
  deletingId: number | null
  /** 点「编辑」时把整行交给页面（页面负责打开弹窗）。 */
  onEdit: (metric: CatalogMetric) => void
}

/**
 * 指标列表。列：ID / 名称 / 数据源 / 分组列 / 频率 / 操作。
 */
export function MetricList({
  isLoading,
  error,
  metrics,
  sources,
  catalog,
  onDelete,
  deletingId,
  onEdit,
}: MetricListProps) {
  const navigate = useNavigate()
  const sourceNameById = new Map((sources ?? []).map((s) => [s.id, s.name]))

  const columns: ColumnsType<CatalogMetric> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 70,
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: '数据源',
      dataIndex: 'source_id',
      key: 'source_id',
      width: 160,
      render: (value: number) => (
        <span className="mono">{sourceNameById.get(value) ?? String(value)}</span>
      ),
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
      title: '时间列',
      dataIndex: 'time_column',
      key: 'time_column',
      width: 120,
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '值列',
      dataIndex: 'value_column',
      key: 'value_column',
      width: 120,
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '频率',
      dataIndex: 'freq',
      key: 'freq',
      width: 100,
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '时区',
      dataIndex: 'source_timezone',
      key: 'source_timezone',
      width: 100,
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '缺失',
      dataIndex: 'missing_policy',
      key: 'missing_policy',
      width: 100,
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_value, row) => (
        <Space size="small">
          {/* ⚠️ 「预览」跳到指标预览页并**带上这个指标** ——
              那边直接就是它的时序图。
              ⚠️ 用 navigate 而不是 `href` —— href 是整页刷新。 */}
          <Button size="small" onClick={() => navigate(`/metrics/preview?metricId=${row.id}`)}>
            预览
          </Button>
          <Button size="small" onClick={() => onEdit(row)}>
            编辑
          </Button>
          <DeleteButton
            target="metric"
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
      data={metrics}
      isEmpty={(data) => data.length === 0}
      emptyTitle="还没有指标"
      emptyHint="先新增数据源，再在这里定义指标"
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
  )
}
