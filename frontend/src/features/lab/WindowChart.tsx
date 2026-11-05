import ReactECharts from 'echarts-for-react'
import { cssVar, invalidateCssVarCache } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import { seriesColors } from '../../lib/palette'
import { detectorLabel } from '../../lib/detectorLabels'
import type { LabWindowDetail } from '../../api/types'

export interface WindowChartProps {
  detail: LabWindowDetail
}

/**
 * 单窗口时序图 —— **窗口内的数据形态**。
 *
 * ⚠️ 这一屏回答的是「这一窗到底长什么样」：
 *   - 实际值一条实线（形态：周期 / 趋势 / 尖峰 / 平坦）
 *   - 每个算法一条虚线基线（它认为「正常」在哪）
 *   - 告警点用散点标出（它认为哪里不正常）
 *
 * 少了这张图，用户只能看「检出 15 个」这种数字，
 * 没法判断这 15 个是尖峰还是噪声边缘。
 *
 * ⚠️ **基线默认收起** —— 六个算法各画一条基线会把形态彻底淹掉。
 *    基线是「参考」，不是主体；点图例能展开。
 */
export function buildWindowOption(props: WindowChartProps, themeMode: 'dark' | 'light' = 'dark') {
  const { detail } = props
  invalidateCssVarCache(themeMode)

  const textPrimary = cssVar('--text-primary', '#fafafa')
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')
  const danger = cssVar('--danger', '#ef4444')
  const colors = seriesColors()

  const series: Array<Record<string, unknown>> = [
    {
      name: '实际值',
      type: 'line',
      data: detail.values,
      symbol: 'none',
      connectNulls: false,
      lineStyle: { color: textPrimary, width: 1.6 },
      z: 4,
    },
  ]

  const legendData: string[] = ['实际值']
  const hidden: Record<string, boolean> = {}

  // ⚠️ 同一**实际**算法只画一次 —— `auto` 常常解析成某个固定算法，
  //    两者画出来一模一样，重复只会让人以为有两个信号。
  const seen = new Set<string>()

  detail.detectors.forEach((item, index) => {
    const key = item.resolved || item.detector
    if (seen.has(key)) return
    seen.add(key)

    const color = colors[index % colors.length]
    const label =
      item.detector === 'auto'
        ? `${detectorLabel(key)}（自动）`
        : detectorLabel(item.detector)

    // 基线 —— 算法认为的「正常值」。有基线的算法才画（Chronos 没有）。
    if (item.baseline.some((v) => v !== null)) {
      series.push({
        name: `${label} 基线`,
        type: 'line',
        data: item.baseline,
        symbol: 'none',
        connectNulls: false,
        lineStyle: { color, width: 1, type: 'dashed', opacity: 0.8 },
        z: 2,
      })
      legendData.push(`${label} 基线`)
      // ⚠️ `legend.selected` 的语义是「true = 选中（显示）」——
      //    基线默认**不选中**，用户点图例才展开。
      hidden[`${label} 基线`] = false
    }

    // 告警点 —— 标在实际值上。
    const points: Array<[number, number]> = []
    item.severity.forEach((severity, i) => {
      const value = detail.values[i]
      if (severity > 0 && value != null) points.push([i, value])
    })
    if (points.length > 0) {
      series.push({
        name: `${label} 告警`,
        type: 'scatter',
        data: points,
        symbolSize: 7,
        itemStyle: { color },
        z: 5,
      })
      legendData.push(`${label} 告警`)
    }
  })

  return {
    series,
    legend: {
      top: 0,
      textStyle: { color: textTertiary, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 8,
      data: legendData,
      selected: hidden,
    },
    xAxis: {
      type: 'category',
      data: detail.timestamps.map((ts) => new Date(ts).toISOString().slice(5, 16).replace('T', ' ')),
      boundaryGap: false,
      axisLabel: { color: textTertiary, fontSize: 11, hideOverlap: true },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: textTertiary, fontSize: 11 },
      splitLine: { lineStyle: { color: border, opacity: 0.45 } },
    },
    grid: { left: 52, right: 20, top: 30, bottom: 34 },
    tooltip: {
      trigger: 'axis',
      textStyle: { color: textPrimary, fontSize: 12 },
      axisPointer: { type: 'cross', lineStyle: { color: danger, opacity: 0.4 } },
    },
  }
}

export function WindowChart({ detail }: WindowChartProps) {
  const themeMode = useThemeModeValue()
  const option = buildWindowOption({ detail }, themeMode)

  return (
    <div className="lab-chart">
      <ReactECharts
        option={option as never}
        notMerge
        style={{ height: 300, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}
