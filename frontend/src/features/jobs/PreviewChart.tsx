import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../lib/echartsCore'
import { Alert } from 'antd'
import { cssVar, cssVarAlpha, invalidateCssVarCache } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import { buildBandSeries } from '../../lib/bands'
import { fmtDateTime } from '../../lib/format'

export interface PreviewChartProps {
  timestamps: string[]
  values: (number | null)[]
  scores: (number | null)[]
  baseline: (number | null)[] | null
  lower: (number | null)[] | null
  upper: (number | null)[] | null
  severity: number[]
  alertThreshold: number
  criticalThreshold: number
  levels: string[]
}

/**
 * option 里我们关心的部分。
 *
 * 用交叉类型：既显式声明单测要断言的字段（name / type / connectNulls …），
 * 又允许 ECharts 的其余配置项存在 —— 否则对象字面量会因为「未知属性」报错。
 */
export interface PreviewOption {
  series: Array<PreviewSeries & Record<string, unknown>>
  xAxis?: unknown
  yAxis?: unknown
  dataZoom?: unknown[]
  legend?: { data?: string[]; top?: number; textStyle?: unknown; itemWidth?: number; itemHeight?: number }
}

/** 单测要断言的字段。 */
export interface PreviewSeries {
  name?: string
  type?: string
  connectNulls?: boolean
  data?: unknown
  stack?: string
  yAxisIndex?: number
  symbolSize?: number
  itemStyle?: { color?: string }
  renderItem?: (...args: unknown[]) => unknown
}

/**
 * 构造预览图的 ECharts option。
 *
 * 抽成纯函数是为了能单测 —— 「缺点断线」「无基线带不画带」这类行为
 * 应该可验证，而不是只能肉眼看图。
 *
 * ⚠️ 颜色全部从 tokens.css 的变量读出实际值（ECharts 不吃 CSS 变量）。
 *
 * @param themeMode 当前主题 —— 变了就清掉色值缓存，让下次读到新主题的颜色
 */
export function buildPreviewOption(
  props: PreviewChartProps,
  themeMode: 'dark' | 'light' = 'dark',
): PreviewOption {
  const {
    timestamps,
    values,
    scores,
    baseline,
    lower,
    upper,
    severity,
    alertThreshold,
    criticalThreshold,
    levels,
  } = props

  // 主题变了就清缓存 —— 否则读到的是上一套主题的颜色。
  // themeMode 参与计算：它变了就重建 option，色值自然也是新的。
  invalidateCssVarCache(themeMode)
  const textPrimary = cssVar('--text-primary', '#fafafa')
  const textSecondary = cssVar('--text-secondary', '#a1a1aa')
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')
  const normal = cssVar('--status-normal', '#10b981')
  const p1 = cssVar('--status-p1', '#f59e0b')
  const p0 = cssVar('--status-p0', '#ef4444')
  const accent = cssVar('--accent-text', '#6da8e3')

  // ⚠️ 按**长度**判断，不只是 null ——
  //    没有基线的算法（如 Chronos）后端会存空数组，
  //    空数组 !== null，会被误判成「有带」→ 画出空的图例项。
  const hasBand =
    (baseline?.length ?? 0) > 0 && (lower?.length ?? 0) > 0 && (upper?.length ?? 0) > 0

  // 告警点按 severity 分三组（0=正常 1=P1 2=P0）
  const p1Points: Array<[number, number]> = []
  const p0Points: Array<[number, number]> = []
  severity.forEach((sev, i) => {
    const v = values[i]
    if (v == null) return
    if (sev === 1) p1Points.push([i, v])
    if (sev === 2) p0Points.push([i, v])
  })

  const series: PreviewOption['series'] = []

  if (hasBand) {
    // 上下界带：custom series 画多边形。
    // ⚠️ **不用 stack + areaStyle** —— stack 是累加的，lower 为负时行为不可预测
    //    （实测会画到 [lower+upper] 而不是 [lower, upper]），详见 lib/bands.ts。
    series.push(
      buildBandSeries({
        lower,
        upper,
        name: '上下界',
        color: normal,
        opacity: 0.12,
        z: 0,
      }) as PreviewSeries & Record<string, unknown>,
    )
    series.push({
      name: '基线',
      type: 'line',
      data: baseline,
      symbol: 'none',
      lineStyle: { color: textSecondary, width: 1.4, type: 'dashed' },
      // ⚠️ 图例 marker 取 itemStyle.color —— 不给就用 ECharts 默认调色板
      itemStyle: { color: textSecondary },
      z: 1,
    })  }

  series.push({
    name: '数值',
    type: 'line',
    data: values,
    // ⚠️ 缺点必须断线 —— ECharts 默认 connectNulls:false，别打开
    connectNulls: false,
    symbol: 'none',
    lineStyle: { color: textPrimary, width: 1.8 },
    itemStyle: { color: textPrimary },
    // 数值是主角，压在分数曲线之上
    z: 3,
  })

  series.push({
    name: '分数',
    type: 'line',
    yAxisIndex: 1,
    data: scores,
    symbol: 'none',
    lineStyle: { color: accent, width: 1, opacity: 0.65 },
    itemStyle: { color: accent },
    z: 1,
  })

  if (p1Points.length > 0) {
    series.push({
      name: `${levels[1] ?? 'P1'} 告警`,
      type: 'scatter',
      data: p1Points,
      symbolSize: 7,
      itemStyle: { color: p1 },
      z: 5,
    })
  }
  if (p0Points.length > 0) {
    series.push({
      name: `${levels[2] ?? 'P0'} 告警`,
      type: 'scatter',
      data: p0Points,
      symbolSize: 11,
      itemStyle: { color: p0 },
      z: 6,
    })
  }

  // 阈值线挂在分数轴上（分数是归一化后的倍数）
  series.push({
    name: '阈值',
    type: 'line',
    yAxisIndex: 1,
    data: [],
    symbol: 'none',
    silent: true,
    markLine: {
      silent: true,
      symbol: 'none',
      label: { color: textTertiary, fontSize: 11 },
      data: [
        {
          yAxis: alertThreshold,
          name: `${levels[1] ?? 'P1'} 门槛`,
          lineStyle: { color: p1, type: 'dashed', width: 1 },
        },
        {
          yAxis: criticalThreshold,
          name: `${levels[2] ?? 'P0'} 门槛`,
          lineStyle: { color: p0, type: 'dashed', width: 1 },
        },
      ],
    },
  })

  return {
    series,
    // 图例：说明每条线/每个点是什么。旧版预览图有这个，别丢。
    legend: {
      top: 0,
      textStyle: { color: textTertiary, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 8,
      // 界带与阈值线是辅助元素，不进图例
      data: series
        .filter((s) => !['上下界', '阈值'].includes(s.name ?? ''))
        .map((s) => s.name as string),
    },
    xAxis: {
      type: 'category',
      data: timestamps.map((ts) => fmtDateTime(ts)),
      boundaryGap: false,
      axisLabel: { color: textTertiary, fontSize: 11, formatter: '{value}' },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: [
      {
        type: 'value',
        scale: true,
        name: '值',
        nameTextStyle: { color: textTertiary, fontSize: 11 },
        axisLabel: { color: textTertiary, fontSize: 11 },
        splitLine: { lineStyle: { color: border, opacity: 0.45 } },
      },
      {
        type: 'value',
        min: 0,
        name: '分数',
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

/**
 * 预览图。
 *
 * 三种边界必须处理（spec §6.1 + §8.2-A）：
 *   1. baseline/lower/upper 为 null → 不画带，给一句说明
 *   2. values 里有 null → 断线（connectNulls 不开）
 *   3. null 直接传给 ECharts（它认 null 表示缺点）
 */
export function PreviewChart(props: PreviewChartProps) {
  // 订阅主题 —— ECharts 不认 CSS 变量，主题变了必须重建 option 才能换色
  const themeMode = useThemeModeValue()
  const hasBand =
    (props.baseline?.length ?? 0) > 0 &&
    (props.lower?.length ?? 0) > 0 &&
    (props.upper?.length ?? 0) > 0
  // themeMode 进依赖：它变了就重建 option（颜色是运行时从 CSS 变量读的）
  const option = buildPreviewOption(props, themeMode)

  return (
    <div className="preview-chart">
      {!hasBand && (
        <Alert
          type="info"
          showIcon
          message="该算法未提供基线带"
          description="只有实际值与分数曲线，没有上下界与基线参考线。"
          style={{ marginBottom: 12 }}
        />
      )}
      <ReactEChartsCore
        echarts={echarts}
        option={option as never}
        notMerge
        style={{ height: 440, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
      <p className="muted preview-chart__note">
        提示：滚轮/拖拽可缩放；下方滑块可拖动选择区间。
        分数为归一化后的偏离倍数，{props.levels[1] ?? 'P1'} 门槛{' '}
        {props.alertThreshold}、{props.levels[2] ?? 'P0'} 门槛 {props.criticalThreshold}。
      </p>
    </div>
  )
}
