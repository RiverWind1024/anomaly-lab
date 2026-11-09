import { useMemo } from 'react'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../lib/echartsCore'
import { cssVar, withAlpha } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'

export interface MonitoringSeries {
  name: string
  data: (number | null)[]
  color: string
  /** 填充线下方面积（流量这类关注总量的用）。 */
  area?: boolean
  /** 0 = 左轴，1 = 右轴。 */
  axis?: 0 | 1
}

export interface MonitoringChartProps {
  /** 已格式化的 X 轴标签（HH:mm）。 */
  times: string[]
  series: MonitoringSeries[]
  height?: number
  leftUnit?: string
  rightUnit?: string
  showRightAxis?: boolean
  /** 数据点少时画点 —— 两个点连成直线会让人以为「在持续上升」。 */
  showSymbol?: boolean
}

/**
 * 监控时序图。
 *
 * ⚠️ `animation: false` —— 每 15 秒整份数据换一次，动画会让曲线一直在抖。
 * ⚠️ 颜色从 CSS 变量读实际值：ECharts 不吃 `var(--accent)`。
 */
export function MonitoringChart({
  times,
  series,
  height = 220,
  leftUnit = '',
  rightUnit = '',
  showRightAxis = false,
  showSymbol = false,
}: MonitoringChartProps) {
  const themeMode = useThemeModeValue()

  const option = useMemo(() => {
    const text = cssVar('--text-secondary', '#9aa3ad')
    const line = cssVar('--border-subtle', '#2b2f36')
    const surface = cssVar('--surface-panel', '#16181c')

    return {
      animation: false,
      grid: { left: 46, right: showRightAxis ? 52 : 16, top: 30, bottom: 24 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: surface,
        borderColor: line,
        textStyle: { color: cssVar('--text-primary', '#e6e9ee'), fontSize: 12 },
        axisPointer: { type: 'line', lineStyle: { color: line } },
        valueFormatter: (value: number | null) =>
          value === null || value === undefined ? '—' : String(Math.round(value * 100) / 100),
      },
      legend: {
        top: 0,
        left: 'center',
        itemWidth: 10,
        itemHeight: 2,
        itemGap: 18,
        textStyle: { color: text, fontSize: 11 },
      },
      xAxis: {
        type: 'category',
        data: times,
        boundaryGap: false,
        axisLine: { lineStyle: { color: line } },
        axisTick: { show: false },
        axisLabel: { color: text, fontSize: 10, hideOverlap: true },
      },
      yAxis: [
        {
          type: 'value',
          name: leftUnit,
          nameTextStyle: { color: text, fontSize: 10 },
          axisLabel: { color: text, fontSize: 10 },
          splitLine: { lineStyle: { color: withAlpha(line, 0.5) } },
        },
        ...(showRightAxis
          ? [
              {
                type: 'value',
                name: rightUnit,
                nameTextStyle: { color: text, fontSize: 10 },
                axisLabel: { color: text, fontSize: 10 },
                splitLine: { show: false },
              },
            ]
          : []),
      ],
      series: series.map((item) => ({
        type: 'line',
        name: item.name,
        data: item.data,
        yAxisIndex: item.axis ?? 0,
        showSymbol,
        symbolSize: 4,
        connectNulls: false,
        lineStyle: { width: 1.5, color: item.color },
        itemStyle: { color: item.color },
        areaStyle: item.area ? { color: withAlpha(item.color, 0.12) } : undefined,
      })),
    }
  }, [themeMode, times, series, leftUnit, rightUnit, showRightAxis, showSymbol])

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option as never}
      notMerge
      style={{ height, width: '100%' }}
      opts={{ renderer: 'canvas' }}
    />
  )
}
