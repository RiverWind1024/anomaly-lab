import { Button, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { StateBoundary } from '../../components/StateBoundary'
import type { SeriesMeta } from '../../api/types'

export interface SeriesOverviewProps {
  isLoading: boolean
  error: unknown
  series: SeriesMeta[] | undefined
  /** 点序列名或「详情」按钮时回调 —— 由页面打开详情抽屉。 */
  onOpenSeries: (seriesId: string) => void
}

/** 时间范围只显示到分钟 —— 秒级对「这段时间有什么数据」没意义。 */
function fmtRange(start: string | null, end: string | null): string {
  if (!start || !end) return '—'
  return `${start.slice(0, 16)} ~ ${end.slice(5, 16)}`
}

/**
 * 序列总览表。
 *
 * 列表项**可点开** —— 序列名与「详情」按钮都会打开详情抽屉，
 * 抽屉里是这条序列的图与检测结果。
 */
export function SeriesOverview({ isLoading, error, series, onOpenSeries }: SeriesOverviewProps) {
  const columns: ColumnsType<SeriesMeta> = [
    {
      title: '序列',
      dataIndex: 'series_id',
      key: 'series_id',
      render: (value: string) => (
        <Button type="link" style={{ padding: 0 }} onClick={() => onOpenSeries(value)}>
          <span className="mono">{value}</span>
        </Button>
      ),
    },
    {
      title: '形态',
      dataIndex: 'metric_class',
      key: 'metric_class',
      width: 160,
    },
    {
      title: '时间范围',
      key: 'time_range',
      width: 250,
      render: (_value, row) => (
        <span className="mono">{fmtRange(row.start_ts, row.end_ts)}</span>
      ),
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
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_value, row) => (
        <Button size="small" onClick={() => onOpenSeries(row.series_id)}>
          详情
        </Button>
      ),
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
