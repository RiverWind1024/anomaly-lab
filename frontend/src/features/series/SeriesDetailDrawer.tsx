import { Descriptions, Drawer, Space, Tag } from 'antd'
import { StateBoundary } from '../../components/StateBoundary'
import { DetectionChart } from '../detections/DetectionChart'
import { useDetectionDetail } from '../detections/queries'
import type { SeriesMeta } from '../../api/types'

export interface SeriesDetailDrawerProps {
  /** 选中的序列；null 表示抽屉关闭。 */
  series: SeriesMeta | null
  onClose: () => void
}

/**
 * 序列详情抽屉。
 *
 * 序列总览原先只有一串纯文本 —— 用户想知道「这条序列长什么样」，
 * 只能自己去别处找。这里直接给图。
 */
export function SeriesDetailDrawer({ series, onClose }: SeriesDetailDrawerProps) {
  const detail = useDetectionDetail(series?.series_id)

  return (
    <Drawer
      open={series !== null}
      onClose={onClose}
      width={880}
      title={series ? <span className="mono">{series.series_id}</span> : ''}
    >
      {series ? (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Descriptions size="small" column={3} bordered>
            <Descriptions.Item label="形态">{series.metric_class}</Descriptions.Item>
            <Descriptions.Item label="点数">{series.n}</Descriptions.Item>
            <Descriptions.Item label="异常点">{series.n_anomalies}</Descriptions.Item>
            <Descriptions.Item label="数据来源">{series.source}</Descriptions.Item>
            <Descriptions.Item label="开始">
              {series.start_ts?.slice(0, 16) ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="结束">
              {series.end_ts?.slice(0, 16) ?? '—'}
            </Descriptions.Item>
          </Descriptions>

          <StateBoundary
            isLoading={detail.isPending}
            error={detail.error}
            data={detail.data}
            bizTitles={{ no_result: '该序列还没有检测结果' }}
            emptyTitle="还没有检测结果"
            emptyHint="先运行 make detect 与 make evaluate"
          >
            {(data) => <DetectionChart data={data} />}
          </StateBoundary>

          <Space size="small" wrap>
            <Tag color="warning">橙色区间 = 误报</Tag>
            <Tag color="error">红色区间 = 漏报</Tag>
          </Space>
        </Space>
      ) : null}
    </Drawer>
  )
}
