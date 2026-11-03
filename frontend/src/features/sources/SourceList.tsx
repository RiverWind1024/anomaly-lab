import { Button, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link, useNavigate } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { DeleteButton } from '../delete/DeleteButton'
import type { Catalog, CatalogSource } from '../../api/types'

export interface SourceListProps {
  isLoading: boolean
  error: unknown
  sources: CatalogSource[] | undefined
  /** 删除影响预览要用的全量数据（catalog）。 */
  catalog: Catalog | undefined
  onDelete: (sourceId: number) => void
  deletingId: number | null
  /** 点「编辑」时把整行交给页面（页面负责打开弹窗）。 */
  onEdit: (source: CatalogSource) => void
  /** 该数据源下有几个指标（列表里直接看得到）。 */
  metricCounts?: Map<number, number>
}

/**
 * 数据源列表。列：ID / 名称 / 指标数 / 类型 / 路径 / 操作。
 */
export function SourceList({
  isLoading,
  error,
  sources,
  catalog,
  onDelete,
  deletingId,
  onEdit,
  metricCounts,
}: SourceListProps) {
  const navigate = useNavigate()

  const columns: ColumnsType<CatalogSource> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 70,
      align: 'right',
      render: (value: number) => <span className="mono dim">{value}</span>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      // 点名字进数据源详情 —— 那里是它的指标列表
      render: (value: string, row) => <Link to={`/sources/${row.id}`}>{value}</Link>,
    },
    {
      title: '指标',
      key: 'metric_count',
      width: 80,
      align: 'right',
      render: (_value, row) => (
        <span className="mono">{metricCounts?.get(row.id) ?? 0}</span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'kind',
      key: 'kind',
      width: 120,
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '路径',
      dataIndex: 'path',
      key: 'path',
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_value, row) => (
        <Space size="small">
          {/* ⚠️ 「预览」跳到指标预览页并**带上这个源** ——
              那边可以直接选指标看图。
              ⚠️ 用 navigate 而不是 `href` —— href 是整页刷新，
              侧边栏状态、滚动位置全丢。 */}
          <Button size="small" onClick={() => navigate(`/metrics/preview?sourceId=${row.id}`)}>
            预览
          </Button>
          <Button size="small" onClick={() => onEdit(row)}>
            编辑
          </Button>
          <DeleteButton
            target="source"
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
      data={sources}
      isEmpty={(data) => data.length === 0}
      emptyTitle="还没有数据源"
      emptyHint="先新增一个数据源，指标才能从它取数"
    >
      {(data) => (
        <Table<CatalogSource>
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
