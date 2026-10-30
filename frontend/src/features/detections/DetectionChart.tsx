import { useMemo } from 'react'
import { Space, Tag } from 'antd'
import ReactECharts from 'echarts-for-react'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import { buildDetectionOption } from './detectionChart'
import type { Badcases } from '../../api/types'

/** 检测详情图：序列值 + 分数 + 阈值 + 误报/漏报区间。 */
export function DetectionChart({ data }: { data: Badcases }) {
  const themeMode = useThemeModeValue()
  const option = useMemo(() => buildDetectionOption({ data }, themeMode), [data, themeMode])

  return (
    <div className="badcase-chart">
      <ReactECharts
        option={option as never}
        notMerge
        style={{ height: 420, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
      <Space size="small" wrap className="badcase-chart__legend">
        <Tag color="warning">橙色区间 = 误报（报了但没异常）</Tag>
        <Tag color="error">红色区间 = 漏报（有异常但没报）</Tag>
      </Space>
    </div>
  )
}
