import { Descriptions, Drawer, Space, Tag } from 'antd'
import { StateBoundary } from '../../components/StateBoundary'
import { usePreview } from '../jobs/queries'
import { AlertChart } from './AlertChart'
import type { AlertEvent } from '../../api/types'
import { fmtFullDateTime } from '../../lib/format'

export interface AlertDetailDrawerProps {
  /** 选中的告警事件；null 表示抽屉关闭。 */
  event: AlertEvent | null
  onClose: () => void
}

function fmtTime(value: string): string {
  return fmtFullDateTime(value)
}

/**
 * 告警详情抽屉。
 *
 * 告警列表原先只有一行文字 —— 用户想知道「到底什么情况」，
 * 却看不到图形。这里直接给出该序列的图，并高亮告警区间。
 */
export function AlertDetailDrawer({ event, onClose }: AlertDetailDrawerProps) {
  const preview = usePreview(
    event?.job_id ?? 0,
    event?.run_id,
    event?.series_id,
    event !== null,
  )

  return (
    <Drawer
      open={event !== null}
      onClose={onClose}
      width={900}
      title={event ? <span className="mono">{event.series_id}</span> : ''}
    >
      {event ? (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="任务">{event.job_name}</Descriptions.Item>
            <Descriptions.Item label="档位">
              <Tag color={(event.level_index ?? 0) >= 3 ? 'error' : 'warning'}>{event.level}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="算法">{event.detector}</Descriptions.Item>
            <Descriptions.Item label="分数类型">{event.score_type}</Descriptions.Item>
            <Descriptions.Item label="开始">{fmtTime(event.start_ts)}</Descriptions.Item>
            <Descriptions.Item label="结束">{fmtTime(event.end_ts)}</Descriptions.Item>
            <Descriptions.Item label="告警点数">{event.n_points}</Descriptions.Item>
            <Descriptions.Item label="峰值分数">{event.max_score.toFixed(2)}</Descriptions.Item>
          </Descriptions>

          <StateBoundary
            isLoading={preview.isPending}
            error={preview.error}
            data={preview.data}
            bizTitles={{ no_run: '这次运行没有序列结果', no_series: '这次运行没有序列结果' }}
            emptyTitle="没有该序列的检测结果"
            emptyHint="该序列可能没有落在检测窗口内"
          >
            {(data) => (
              <AlertChart preview={data} startTs={event.start_ts} endTs={event.end_ts} />
            )}
          </StateBoundary>

          <Space size="small" wrap>
            <Tag color="error">红色区间 = 本次告警</Tag>
            <Tag>虚线 = 该点的告警阈值</Tag>
          </Space>
        </Space>
      ) : null}
    </Drawer>
  )
}
