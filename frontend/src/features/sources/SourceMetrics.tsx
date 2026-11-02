import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import type { CatalogMetric, CatalogSource } from '../../api/types'

/**
 * 指标一览 —— 数据源列表页的次级区块。
 *
 * ⚠️ **只读**：编辑与删除在数据源详情页里做，这里只是让人一眼看到
 *    「每个源取数的方式是什么」，不用点进去。
 */
export function SourceMetrics({
  metrics,
  sources,
}: {
  metrics: CatalogMetric[]
  sources: CatalogSource[]
}) {
  const sourceNameById = new Map(sources.map((s) => [s.id, s.name]))

  const columns: ColumnsType<CatalogMetric> = [
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
      width: 160,
      render: (value: string, row) => <Link to={`/metrics/${row.id}`}>{value}</Link>,
    },
    {
      title: '数据源',
      dataIndex: 'source_id',
      key: 'source_id',
      width: 140,
      render: (value: number) => (
        <span className="mono dim">{sourceNameById.get(value) ?? String(value)}</span>
      ),
    },
    {
      title: '频率',
      dataIndex: 'freq',
      key: 'freq',
      width: 90,
      align: 'right',
      render: (value: string) => <span className="mono">{value}</span>,
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
      title: '分组列',
      dataIndex: 'group_column',
      key: 'group_column',
      width: 120,
      render: (value: string | null) =>
        value ? <span className="mono dim">{value}</span> : <span className="dim">—</span>,
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
  ]

  return (
    <Table<CatalogMetric>
      rowKey="id"
      columns={columns}
      dataSource={metrics}
      size="middle"
      pagination={false}
      scroll={{ x: 'max-content' }}
    />
  )
}
