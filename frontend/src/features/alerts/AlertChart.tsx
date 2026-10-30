import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import { cssVar, cssVarAlpha, invalidateCssVarCache, withAlpha } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import type { Preview } from '../../api/types'

export interface AlertChartProps {
  preview: Preview
  /** 要高亮的区间（告警事件的时间范围）。 */
  startTs: string
  endTs: string
}

export interface AlertSeries {
  name?: string
  type?: string
  data?: unknown
  yAxisIndex?: number
  symbol?: string
  lineStyle?: { color?: string; width?: number; type?: string; opacity?: number }
  markArea?: { silent?: boolean; data?: unknown[] }
}

export interface AlertOption {
  series: Array<AlertSeries & Record<string, unknown>>
  xAxis?: unknown
  yAxis?: unknown
  dataZoom?: unknown[]
  legend?: { data?: string[]; top?: number; textStyle?: unknown; itemWidth?: number; itemHeight?: number }
  title?: { text?: string; top?: number; textStyle?: unknown }
}

/**
 * 找出告警区间在时间轴上的下标范围。
 *
 * ⚠️ 时间戳是**同格式**的 ISO 秒精度字符串（两边都来自 numpy datetime64[s]），
 *    所以可以直接比字符串 —— 不要去解析时间戳，徒增出错面。
 */
export function rangeIndices(
  timestamps: string[],
  startTs: string,
  endTs: string,
): [number, number] | null {
  let start = -1
  let end = -1
  timestamps.forEach((value, index) => {
    if (start < 0 && value >= startTs) start = index
    if (value <= endTs) end = index
  })
  if (start < 0 || end < start) return null
  return [start, end]
}

/**
 * 构造告警详情图的 option：序列值 + 分数 + 告警区间高亮。
 */
export function buildAlertOption(
  props: AlertChartProps,
  themeMode: 'dark' | 'light' = 'dark',
): AlertOption {
  const { preview, startTs, endTs } = props
  invalidateCssVarCache(themeMode)

  const textPrimary = cssVar('--text-primary', '#fafafa')
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')
  const accent = cssVar('--accent-text', '#6da8e3')
  const p0 = cssVar('--status-p0', '#ef4444')
  const p1 = cssVar('--status-p1', '#f59e0b')

  const range = rangeIndices(preview.timestamps, startTs, endTs)
  const areas: unknown[] = range
    ? [
        [
          {
            xAxis: range[0],
            itemStyle: {
              color: withAlpha(p0, 0.32),
              borderColor: withAlpha(p0, 0.75),
              borderWidth: 1,
            },
          },
          { xAxis: range[1] },
        ],
      ]
    : []

  // 逐点阈值：P0 用严重阈值，其余用告警阈值
  const thresholds = preview.scores.map((_score, index) =>
    (preview.severity[index] ?? 0) >= 3 ? preview.critical_threshold : preview.alert_threshold,
  )

  /**
   * 默认聚焦到告警区间附近。
   *
   * ⚠️ 一次运行有几百个点，告警可能只有几个 ——
   *    不聚焦的话用户得自己拖到底去找那一段。
   */
  const focus = (() => {
    if (!range) return { startValue: 0, endValue: preview.timestamps.length - 1 }
    const [from, to] = range
    const span = to - from
    const pad = Math.max(20, span * 3)
    const start = Math.max(0, from - pad)
    const end = Math.min(preview.timestamps.length - 1, to + pad)
    return { startValue: start, endValue: end }
  })()

  return {
    series: [
      {
        name: '数值',
        type: 'line',
        data: preview.values,
        symbol: 'none',
        lineStyle: { color: textPrimary, width: 1.6 },
        markArea: { silent: true, data: areas },
      },
      {
        name: '分数',
        type: 'line',
        yAxisIndex: 1,
        data: preview.scores,
        symbol: 'none',
        lineStyle: { color: accent, width: 1, opacity: 0.7 },
      },
      {
        name: '告警阈值',
        type: 'line',
        yAxisIndex: 1,
        data: thresholds,
        symbol: 'none',
        lineStyle: { color: p1, width: 1, type: 'dashed' },
      },
    ],
    title: {
      text: `${preview.series_id} · ${preview.detector} · ${preview.score_type}`,
      top: 0,
      textStyle: { color: textTertiary, fontSize: 12 },
    },
    legend: {
      top: 26,
      textStyle: { color: textTertiary, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 8,
      data: ['数值', '分数', '告警阈值'],
    },
    xAxis: {
      type: 'category',
      data: preview.timestamps,
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
      { type: 'inside', ...focus },
      {
        type: 'slider',
        height: 18,
        bottom: 12,
        borderColor: border,
        fillerColor: cssVarAlpha('--text-tertiary', 0.18, 'rgba(120,120,120,0.18)'),
        handleStyle: { color: border },
        textStyle: { color: textTertiary, fontSize: 10 },
        ...focus,
      },
    ],
  }
}

/** 告警详情图：序列值 + 分数 + 告警区间高亮。 */
export function AlertChart({ preview, startTs, endTs }: AlertChartProps) {
  const themeMode = useThemeModeValue()
  const option = useMemo(
    () => buildAlertOption({ preview, startTs, endTs }, themeMode),
    [preview, startTs, endTs, themeMode],
  )
  return (
    <div className="alert-chart">
      <ReactECharts
        option={option as never}
        notMerge
        style={{ height: 360, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}
