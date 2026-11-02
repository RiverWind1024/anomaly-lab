import ReactECharts from 'echarts-for-react'
import { cssVar, cssVarAlpha, invalidateCssVarCache } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import type { CompareDetector } from '../../api/types'

export interface CompareChartProps {
  timestamps: string[]
  values: (number | null)[]
  detectors: CompareDetector[]
}

export interface CompareSeries {
  name?: string
  type?: string
  data?: unknown
  connectNulls?: boolean
  symbolSize?: number
  lineStyle?: { color?: string; width?: number; type?: string; opacity?: number }
  itemStyle?: { color?: string }
}

export interface CompareOption {
  series: Array<CompareSeries & Record<string, unknown>>
  legend?: { data?: string[]; top?: number; textStyle?: unknown; itemWidth?: number; itemHeight?: number }
  xAxis?: unknown
  yAxis?: unknown
  dataZoom?: unknown[]
}

/**
 * 对比图的分类色。
 *
 * 来自 tokens.css 的 `--series-1..5`（单一视觉来源）。
 *
 * ⚠️ 旧代码的 `COMPARE_COLORS` 里 `#d97706` 与 P1 告警色撞色 ——
 *    `--series-*` 已按 D17 解出与告警三档色相错开 ≥35°。
 */
export function seriesColors(): string[] {
  return [
    cssVar('--series-1', '#7acd51'),
    cssVar('--series-2', '#81c4da'),
    cssVar('--series-3', '#6161d1'),
    cssVar('--series-4', '#c079d8'),
    cssVar('--series-5', '#ca4994'),
  ]
}

/**
 * 构造多算法对比图的 ECharts option。
 *
 * 照搬旧 `renderCompareChart`：
 *   - 实际值一条实线
 *   - 每个算法一条虚线基线
 *   - 每个算法一组告警散点（severity > 0 且该点有值）
 */
export function buildCompareOption(
  props: CompareChartProps,
  themeMode: 'dark' | 'light' = 'dark',
): CompareOption {
  const { timestamps, values, detectors } = props

  invalidateCssVarCache(themeMode)

  const textPrimary = cssVar('--text-primary', '#fafafa')
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')
  const colors = seriesColors()

  const series: CompareOption['series'] = [
    {
      name: '实际值',
      type: 'line',
      data: values,
      connectNulls: false,
      symbol: 'none',
      lineStyle: { color: textPrimary, width: 1.8 },
      z: 3,
    },
  ]

  const legend: string[] = ['实际值']

  detectors.forEach((detector, index) => {
    const color = colors[index % colors.length]

    if (detector.baseline) {
      series.push({
        name: `${detector.name} 基线`,
        type: 'line',
        data: detector.baseline,
        connectNulls: false,
        symbol: 'none',
        lineStyle: { color, width: 1, type: 'dashed' },
        z: 2,
      })
      legend.push(`${detector.name} 基线`)
    }

    // 告警点：severity > 0 且该点有实际值（缺点没有值可标）
    const points: Array<[number, number]> = []
    detector.severity.forEach((severity, i) => {
      const value = values[i]
      if (severity > 0 && value != null) points.push([i, value])
    })
    if (points.length > 0) {
      series.push({
        name: `${detector.name} 告警`,
        type: 'scatter',
        data: points,
        symbolSize: 7,
        itemStyle: { color },
        z: 5,
      })
      legend.push(`${detector.name} 告警`)
    }
  })

  return {
    series,
    legend: {
      top: 0,
      textStyle: { color: textTertiary, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 8,
      data: legend,
    },
    xAxis: {
      type: 'category',
      data: timestamps,
      boundaryGap: false,
      axisLabel: { color: textTertiary, fontSize: 11 },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: textTertiary, fontSize: 11 },
      splitLine: { lineStyle: { color: border, opacity: 0.45 } },
    },
    dataZoom: [
      { type: 'inside' },
      {
        type: 'slider',
        height: 18,
        bottom: 12,
        borderColor: border,
        fillerColor: cssVarAlpha('--text-tertiary', 0.18, 'rgba(120,120,120,0.18)'),
        handleStyle: { color: border },
        textStyle: { color: textTertiary, fontSize: 11 },
      },
    ],
  }
}

/**
 * 多算法对比图：各算法的基线与告警点叠在同一张图上
 * （这是旧版 `renderCompareChart` 的行为，别漏）。
 */
export function CompareChart(props: CompareChartProps) {
  const themeMode = useThemeModeValue()
  const option = buildCompareOption(props, themeMode)

  return (
    <div className="compare-chart">
      <ReactECharts
        option={option as never}
        notMerge
        style={{ height: 420, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}
