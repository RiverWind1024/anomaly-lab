/**
 * 检测图的 option 构造（纯函数，不碰 React）。
 *
 * 单独拆出来是为了能脱离组件单测 —— 图里画的东西（异常区间有没有真画出来）
 * 之前完全没有测试覆盖。
 */

import { cssVar, cssVarAlpha, invalidateCssVarCache, withAlpha } from '../../theme/cssVar'
import { buildBandSeries } from '../../lib/bands'
import type { Badcases } from '../../api/types'

export interface DetectionChartProps {
  data: Badcases
}

export interface DetectionSeries {
  name?: string
  type?: string
  data?: unknown
  yAxisIndex?: number
  symbol?: string
  stack?: string
  z?: number
  silent?: boolean
  connectNulls?: boolean
  tooltip?: { show?: boolean }
  itemStyle?: { color?: string }
  lineStyle?: { color?: string; width?: number; type?: string; opacity?: number }
  areaStyle?: { color?: string; opacity?: number }
  markArea?: { silent?: boolean; data?: unknown[] }
  renderItem?: (...args: unknown[]) => unknown
}

export interface DetectionOption {
  series: Array<DetectionSeries & Record<string, unknown>>
  xAxis?: unknown
  yAxis?: unknown
  dataZoom?: unknown[]
  legend?: { data?: string[]; top?: number; textStyle?: unknown; itemWidth?: number; itemHeight?: number }
  title?: { text?: string; top?: number; textStyle?: unknown }
}

/**
 * 把检测点索引压成**连续区间**。
 *
 * `badcases[].indices` 是一串点索引（如 [3,4,5,9]），
 * 直接用第一个和最后一个当区间会把中间的正常点也框进去。
 */
export function toRanges(indices: number[]): Array<[number, number]> {
  if (!indices.length) return []
  const sorted = [...indices].sort((a, b) => a - b)
  const ranges: Array<[number, number]> = []
  let start = sorted[0]
  let prev = sorted[0]
  for (const index of sorted.slice(1)) {
    if (index === prev + 1) {
      prev = index
      continue
    }
    ranges.push([start, prev])
    start = index
    prev = index
  }
  ranges.push([start, prev])
  return ranges
}

/** 检测偏差类型的展示名。 */
export function badcaseLabel(kind: string): string {
  if (kind === 'false_positive') return '误报'
  if (kind === 'false_negative') return '漏报'
  return kind
}

export function badcaseColor(kind: string, p0: string, p1: string): string {
  if (kind === 'false_positive') return p1
  if (kind === 'false_negative') return p0
  return p0
}

/**
 * 构造检测详情图的 option。
 *
 * ⚠️ **必须用 `badcases[].indices` 真画出异常区间** —— 旧版写的是
 *    `markArea: data.badcases.length ? {} : undefined`，空对象 markArea 等于没画，
 *    异常区间从来没显示过。
 */
export function buildDetectionOption(
  props: DetectionChartProps,
  themeMode: 'dark' | 'light' = 'dark',
): DetectionOption {
  const { data } = props
  invalidateCssVarCache(themeMode)

  const textSecondary = cssVar('--text-secondary', '#a1a1aa')
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')
  // ⚠️ 主数据元素（信号本身）用**这一个数据色** —— 分数线退成中性色，
  //    否则整屏没有数据色（app-screens §6.4 no-data-hue）
  const chart = cssVar('--chart', '#6da8e3')
  const p0 = cssVar('--status-p0', '#ef4444')
  const p1 = cssVar('--status-p1', '#f59e0b')

  // 异常区间：每个 badcase 一组，按类型着色
  const areas: unknown[] = []
  for (const item of data.badcases) {
    const color = badcaseColor(item.kind, p0, p1)
    for (const [start, end] of toRanges(item.indices)) {
      areas.push([
        { xAxis: start, itemStyle: { color: withAlpha(color, 0.22) } },
        { xAxis: end },
      ])
    }
  }

  const threshold = Number(data.threshold || 0)
  const thresholdLine = data.scores.map(() => threshold)

  // 基线带：custom series 画多边形（**不用 stack** —— 负值下 stack 的行为不可预测，
  // 实测会画到 [lower+upper] 而不是 [lower, upper]，详见 lib/bands.ts）。
  // ⚠️ 按**长度**判断，不只判 null —— 后端对不支持基线的检测器存空数组。
  const hasBand =
    (data.baseline?.length ?? 0) > 0 &&
    (data.lower?.length ?? 0) > 0 &&
    (data.upper?.length ?? 0) > 0
  // 预测区间的带是「模型的不确定性」，用中性色；告警边界带用状态色
  const isPrediction = data.band_kind === 'prediction_interval'
  const bandColor = isPrediction ? textSecondary : p1

  const series: Array<DetectionSeries & Record<string, unknown>> = []

  if (hasBand) {
    series.push(
      buildBandSeries({
        lower: data.lower,
        upper: data.upper,
        name: isPrediction ? '预测区间' : '容忍带',
        color: bandColor,
        opacity: 0.1,
        z: 0,
      }) as DetectionSeries & Record<string, unknown>,
    )
    series.push({
      name: isPrediction ? '预测基线' : '基线',
      type: 'line',
      data: data.baseline,
      symbol: 'none',
      lineStyle: { color: textSecondary, width: 1.3, type: 'dashed', opacity: 0.85 },
      // ⚠️ 图例 marker 取的是 itemStyle.color，不是 lineStyle.color ——
      //    不显式给，图例就会用 ECharts 默认调色板，颜色与线对不上
      itemStyle: { color: textSecondary },
      connectNulls: false,
      z: 1,
    })
  }

  series.push(
    {
      name: '数值',
      type: 'line',
      data: data.values,
      symbol: 'none',
      lineStyle: { color: chart, width: 1.6 },
      // ⚠️ 线下压一层极淡的同色 —— 主数据元素要真的带上那一个色相，
      //    光靠一条 1.6px 的线在整屏里几乎看不见颜色
      areaStyle: { color: chart, opacity: 0.09 },
      itemStyle: { color: chart },
      markArea: { silent: true, data: areas },
      z: 3,
    },
    {
      name: '分数',
      type: 'line',
      yAxisIndex: 1,
      data: data.scores,
      symbol: 'none',
      lineStyle: { color: textSecondary, width: 1, opacity: 0.7 },
      itemStyle: { color: textSecondary },
      z: 1,
    },
    {
      name: '阈值',
      type: 'line',
      yAxisIndex: 1,
      data: thresholdLine,
      symbol: 'none',
      lineStyle: { color: p1, width: 1, type: 'dashed' },
      itemStyle: { color: p1 },
      z: 2,
    },
  )

  const legendData = ['数值', '分数', '阈值']
  if (hasBand) {
    legendData.unshift(isPrediction ? '预测区间' : '容忍带')
    legendData.unshift(isPrediction ? '预测基线' : '基线')
  }

  return {
    series,
    title: {
      text: `${data.series_id} / ${data.detector} / ${data.score_type}`,
      top: 0,
      textStyle: { color: textTertiary, fontSize: 12 },
    },
    legend: {
      top: 26,
      textStyle: { color: textTertiary, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 8,
      data: legendData,
    },
    xAxis: {
      type: 'category',
      data: data.timestamps,
      boundaryGap: false,
      axisLabel: { color: textTertiary, fontSize: 11 },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: [
      {
        type: 'value',
        name: '值',
        scale: true,
        nameTextStyle: { color: textTertiary, fontSize: 11 },
        axisLabel: { color: textTertiary, fontSize: 11 },
        splitLine: { lineStyle: { color: border, opacity: 0.45 } },
      },
      {
        type: 'value',
        name: '分数',
        min: 0,
        nameTextStyle: { color: textTertiary, fontSize: 11 },
        axisLabel: { color: textTertiary, fontSize: 11 },
        splitLine: { show: false },
      },
    ],
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
