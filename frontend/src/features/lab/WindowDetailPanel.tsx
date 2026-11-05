import { Alert, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { getLabWindow } from '../../api/platform'
import type { LabSpec } from '../../api/types'
import { detectorLabel } from '../../lib/detectorLabels'
import { WindowChart } from './WindowChart'

export interface WindowDetailPanelProps {
  /** 实验用的 spec —— 原样转发，后端才能取到同一批数据。 */
  spec: LabSpec
  seriesId: string
  windowIndex: number
  /** 要画哪些算法。 */
  detectors: string[]
}

/**
 * 展开行里的窗口时序图。
 *
 * ⚠️ **按需拉取** —— 展开时才请求，折叠的行不占带宽。
 */
export function WindowDetailPanel({
  spec,
  seriesId,
  windowIndex,
  detectors,
}: WindowDetailPanelProps) {
  const query = useQuery({
    queryKey: ['lab-window', spec.metric_id, spec.source_id, seriesId, windowIndex, detectors],
    queryFn: () =>
      getLabWindow({
        kind: spec.kind as 'metric' | 'sql',
        start: spec.start,
        end: spec.end,
        metric_id: spec.metric_id ?? undefined,
        source_id: spec.source_id ?? undefined,
        sql: spec.sql ?? undefined,
        time_column: spec.time_column ?? undefined,
        value_column: spec.value_column ?? undefined,
        group_column: spec.group_column,
        time_format: spec.time_format,
        source_timezone: spec.source_timezone,
        freq: spec.freq ?? undefined,
        missing_policy: spec.missing_policy ?? undefined,
        max_series: spec.max_series,
        sampling: {
          ...spec.sampling,
          mode: spec.sampling.mode as 'recent' | 'even' | 'stratified',
        },
        series_id: seriesId,
        window_index: windowIndex,
        detectors,
      }),
    enabled: true,
  })

  if (query.isPending) {
    return (
      <div className="lab-window__loading">
        <Spin size="small" />
      </div>
    )
  }

  if (query.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message="这一窗的时序数据拉取失败"
        description={query.error instanceof Error ? query.error.message : '未知错误'}
      />
    )
  }

  const detail = query.data

  return (
    <div className="lab-window">
      <div className="lab-window__legend">
        {detail.detectors.map((item) => (
          <span key={item.detector} className="lab-window__chip">
            {detectorLabel(item.detector)}
            {item.resolved !== item.detector ? `（实际用 ${detectorLabel(item.resolved)}）` : ''}
            <span className="mono"> · 告警 {item.n_alerts}</span>
          </span>
        ))}
      </div>
      <WindowChart detail={detail} />
    </div>
  )
}
