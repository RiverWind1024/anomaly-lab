import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { StateBoundary } from '../../components/StateBoundary'
import type { SeriesMeta } from '../../api/types'

interface SeriesOverviewProps {
  isLoading: boolean
  error: unknown
  series: SeriesMeta[] | undefined
}

/**
 * 序列总览表。
 *
 * 旧首页只显示序列**计数**，这里是真正的列表（spec §8.2-C 新增项）。
 */
export function SeriesOverview({ isLoading, error, series }: SeriesOverviewProps) {
  const columns: ColumnsType<SeriesMeta> = [
    {
      title: '序列',
      dataIndex: 'series_id',
      key: 'series_id',
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '形态',
      dataIndex: 'metric_class',
      key: 'metric_class',
      width: 180,
    },
    {
      title: '点数',
      dataIndex: 'n',
      key: 'n',
      width: 100,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '异常点',
      dataIndex: 'n_anomalies',
      key: 'n_anomalies',
      width: 100,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
  ]

  return (
    <StateBoundary
      isLoading={isLoading}
      error={error}
      data={series}
      isEmpty={(data) => data.length === 0}
      emptyTitle="还没有可分析的序列"
      emptyHint="先运行 make generate 生成合成数据"
    >
      {(data) => (
        <Table<SeriesMeta>
          rowKey="series_id"
          columns={columns}
          dataSource={data}
          size="middle"
          pagination={{ pageSize: 20, showSizeChanger: true }}
          scroll={{ x: 'max-content' }}
        />
      )}
    </StateBoundary>
  )
}
