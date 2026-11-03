import { useMemo } from 'react'
import { Space } from 'antd'
import ReactECharts from 'echarts-for-react'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import { buildDetectionOption } from './detectionChart'
import type { Badcases } from '../../api/types'

/** 检测详情图：序列值 + 分数 + 阈值 + 误报/漏报区间 + 基线带。 */
export function DetectionChart({ data }: { data: Badcases }) {
  const themeMode = useThemeModeValue()
  const option = useMemo(() => buildDetectionOption({ data }, themeMode), [data, themeMode])
  const hasBand =
    (data.baseline?.length ?? 0) > 0 &&
    (data.lower?.length ?? 0) > 0 &&
    (data.upper?.length ?? 0) > 0

  return (
    <div className="badcase-chart">
      <ReactECharts
        option={option as never}
        notMerge
        style={{ height: 420, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
      {/* ⚠️ 用状态色的 pill，不用 AntD 的 preset Tag —— 它的橙/红文字对比度不够 taste-skill-ignore */}
      <Space size="small" wrap className="badcase-chart__legend">
        <span className="pill pill--p1">橙色区间 = 误报（报了但没异常）</span>
        <span className="pill pill--p0">红色区间 = 漏报（有异常但没报）</span>
        {/* 带的两种语义要分开说 —— 预测区间不是告警边界 */}
        {hasBand && (
          <span className="pill">
            {data.band_kind === 'prediction_interval'
              ? '灰带 = 模型预测区间（不是告警边界）'
              : '橙带 = 告警容忍带（出带即告警）'}
          </span>
        )}
      </Space>
    </div>
  )
}
