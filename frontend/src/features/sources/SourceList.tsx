import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
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
}

/**
 * 数据源列表。列：ID / 名称 / 类型 / 路径 / 操作。
 */
export function SourceList({
  isLoading,
  error,
  sources,
  catalog,
  onDelete,
  deletingId,
}: SourceListProps) {
  const columns: ColumnsType<CatalogSource> = [
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
      title: '类型',
      dataIndex: 'kind',
      key: 'kind',
      width: 120,
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '路径',
      dataIndex: 'path',
      key: 'path',
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_value, row) => (
        <DeleteButton
          target="source"
          id={row.id}
          name={row.name}
          catalog={catalog}
          loading={deletingId === row.id}
          onConfirm={() => onDelete(row.id)}
        />
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
