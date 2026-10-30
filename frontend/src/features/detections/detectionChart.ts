/**
 * 检测图的 option 构造（纯函数，不碰 React）。
 *
 * 单独拆出来是为了能脱离组件单测 —— 图里画的东西（异常区间有没有真画出来）
 * 之前完全没有测试覆盖。
 */

import { cssVar, cssVarAlpha, invalidateCssVarCache, withAlpha } from '../../theme/cssVar'
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
  lineStyle?: { color?: string; width?: number; type?: string; opacity?: number }
  markArea?: { silent?: boolean; data?: unknown[] }
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

  const textPrimary = cssVar('--text-primary', '#fafafa')
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')
  const accent = cssVar('--accent-text', '#6da8e3')
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

  return {
    series: [
      {
        name: '数值',
        type: 'line',
        data: data.values,
        symbol: 'none',
        lineStyle: { color: textPrimary, width: 1.6 },
        markArea: { silent: true, data: areas },
      },
      {
        name: '分数',
        type: 'line',
        yAxisIndex: 1,
        data: data.scores,
        symbol: 'none',
        lineStyle: { color: accent, width: 1, opacity: 0.7 },
      },
      {
        name: '阈值',
        type: 'line',
        yAxisIndex: 1,
        data: thresholdLine,
        symbol: 'none',
        lineStyle: { color: p1, width: 1, type: 'dashed' },
      },
    ],
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
      data: ['数值', '分数', '阈值'],
    },
    xAxis: {
      type: 'category',
      data: data.timestamps,
      boundaryGap: false,
      axisLabel: { color: textTertiary, fontSize: 10 },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: [
      {
        type: 'value',
        name: '值',
        scale: true,
        nameTextStyle: { color: textTertiary, fontSize: 11 },
        axisLabel: { color: textTertiary, fontSize: 10 },
        splitLine: { lineStyle: { color: border, opacity: 0.45 } },
      },
      {
        type: 'value',
        name: '分数',
        min: 0,
        nameTextStyle: { color: textTertiary, fontSize: 11 },
        axisLabel: { color: textTertiary, fontSize: 10 },
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
        textStyle: { color: textTertiary, fontSize: 10 },
      },
    ],
  }
}
