import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../lib/echartsCore'
import { cssVar, invalidateCssVarCache } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import { seriesColors } from '../../lib/palette'
import type { LabDetectorRun } from '../../api/types'

export interface SensitivityChartProps {
  runs: LabDetectorRun[]
  /** 倍数档位（升序）—— 与后端的 `multipliers` 一致。 */
  multipliers: string[]
}

/**
 * 倍数敏感性曲线：**检出点随阈值倍数怎么变**。
 *
 * 这一张图回答的是「这个算法好不好调」：
 *   - 线陡 —— 阈值动一点检出量就大变，上线后难调；
 *   - 线平 —— 阈值怎么设都差不多，稳。
 *
 * ⚠️ 纵轴是**检出点数**不是比例 —— 各检测器跑的窗口一样多，
 *    点数可以直接横向比。
 */
export function buildSensitivityOption(
  props: SensitivityChartProps,
  themeMode: 'dark' | 'light' = 'dark',
) {
  const { runs, multipliers } = props
  invalidateCssVarCache(themeMode)

  const textPrimary = cssVar('--text-primary', '#fafafa')
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')
  const colors = seriesColors()

  const series = runs.map((run, index) => ({
    name: run.detector,
    type: 'line',
    data: multipliers.map((m) => run.aggregate.sensitivity[m] ?? 0),
    symbol: 'circle',
    symbolSize: 6,
    lineStyle: { color: colors[index % colors.length], width: 1.8 },
    itemStyle: { color: colors[index % colors.length] },
    z: 3,
  }))

  return {
    series,
    legend: {
      top: 0,
      textStyle: { color: textTertiary, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 8,
      data: runs.map((run) => run.detector),
    },
    xAxis: {
      type: 'category',
      name: '告警倍数',
      nameTextStyle: { color: textTertiary, fontSize: 11 },
      data: multipliers,
      axisLabel: { color: textTertiary, fontSize: 11 },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: {
      type: 'value',
      name: '检出点',
      nameTextStyle: { color: textTertiary, fontSize: 11 },
      minInterval: 1,
      axisLabel: { color: textTertiary, fontSize: 11 },
      splitLine: { lineStyle: { color: border, opacity: 0.45 } },
    },
    grid: { left: 48, right: 16, top: 30, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      textStyle: { color: textPrimary, fontSize: 12 },
    },
  }
}

export function SensitivityChart(props: SensitivityChartProps) {
  const themeMode = useThemeModeValue()
  const option = buildSensitivityOption(props, themeMode)

  return (
    <div className="lab-chart">
      <ReactEChartsCore
        echarts={echarts}
        option={option as never}
        notMerge
        style={{ height: 280, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}
