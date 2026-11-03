/**
 * 异常分数轨迹的几何计算 —— 纯函数，不碰 DOM。
 *
 * ⚠️ 抽成纯函数是为了能单测：窗口裁剪、y 轴上限、阈值线位置、
 *    峰值点、x 轴刻度这些「算错了肉眼看不出来」的行为应该可验证。
 *
 * 画法遵循 app-screens §6：
 *   - 一条线，一种色（主数据元素的那一个色相）
 *   - 网格线 3-4 条，1px，只有横向
 *   - 阈值是 1px 虚线，右端带名字
 *   - 峰值标一个点 + 一行小字
 */

import { parseTs } from '../../lib/format'

const HOUR = 3600 * 1000

export interface TrailPoint {
  /** 毫秒时间戳 */
  t: number
  /** 异常分数（σ） */
  s: number
  /** 原始值 */
  v: number | null
  /** 在原数组里的下标 —— 悬停提示要用原时间戳 */
  i: number
}

export interface TrailOptions {
  width: number
  height: number
  /** 时间窗口（小时）；null = 全部 */
  windowHours: number | null
  alertThreshold: number
  criticalThreshold: number
  /** 是否画告警事件条带 */
  withStrips?: boolean
}

export interface TrailGeometry {
  /** 全部点 */
  points: TrailPoint[]
  /** 落在当前窗口里的点 */
  view: TrailPoint[]
  vMin: number
  vMax: number
  /** y 轴上限（向上取整到 5 的倍数） */
  yMax: number
  padL: number
  padR: number
  padT: number
  plotW: number
  plotH: number
  plotBottom: number
  /** x 轴刻度（毫秒时间戳） */
  ticks: number[]
  /** 是否显示 x 轴标签（窄屏只显示时间） */
  wideLabels: boolean
  peak: TrailPoint | null
  /** 峰值是否超出了 y 轴上限 */
  clipped: boolean
  /** 曲线路径 */
  path: string
  /** 曲线下的填充路径 */
  area: string
  /** 事件条带两行的 y 坐标 */
  p0RowY: number
  p1RowY: number
  stripH: number
  showStripLabels: boolean
  /** 时间 → x 坐标 */
  x: (t: number) => number
  /** 分数 → y 坐标 */
  y: (s: number) => number
}

/** 时间戳 → 毫秒（兼容不带时区的 UTC 文本）。 */
function toMs(ts: string): number {
  return parseTs(ts)
}

/**
 * 选一个「好看」的刻度步长（小时）。
 *
 * 步长要同时满足：整小时、点数不过密、标签放得下。
 */
export function niceStep(spanHours: number, plotWidth: number, wideLabel: boolean): number {
  const steps = [1, 2, 3, 6, 12, 24]
  // ⚠️ 12px 的等宽时间标签约 6px/字符 —— 「MM-DD HH:mm」要 66px
  const labelPx = wideLabel ? 70 : 48
  for (const step of steps) {
    const count = spanHours / step
    if (count <= 12 && plotWidth / count >= labelPx) return step
  }
  return 48
}

/**
 * 计算轨迹的几何。
 *
 * @param timestamps 时间戳数组（UTC 文本）
 * @param scores 异常分数数组
 * @param values 原始值数组（可含 null）
 */
export function buildTrail(
  timestamps: string[],
  scores: (number | null)[],
  values: (number | null)[] | undefined,
  options: TrailOptions,
): TrailGeometry | null {
  const { width, height, windowHours, alertThreshold, criticalThreshold } = options
  const withStrips = options.withStrips !== false

  const points: TrailPoint[] = []
  for (let i = 0; i < timestamps.length; i++) {
    const s = scores[i]
    if (s == null || !Number.isFinite(s)) continue
    points.push({ t: toMs(timestamps[i]), s, v: values?.[i] ?? null, i })
  }
  if (points.length < 2) return null

  const tMax = points[points.length - 1].t
  const tMin = points[0].t
  const from = windowHours === null ? tMin : tMax - windowHours * HOUR
  let view = points.filter((p) => p.t >= from)
  if (view.length < 2) view = points.slice(-2)
  const vMin = view[0].t
  const vMax = view[view.length - 1].t

  let peak = view[0]
  for (const p of view) if (p.s > peak.s) peak = p

  /**
   * y 轴上限：收到**参考线的两倍左右**。
   *
   * ⚠️ 分数大多在 0-3 之间，峰值偶尔冲到 13 —— 若按峰值定标，
   *    整条线会贴在底部，上面留一大片空白（app-screens §6.1）。
   *    超出上限的峰值画在顶边上并标注真实数值，不假装它在刻度里。
   */
  const refLine = alertThreshold > 0 ? alertThreshold : criticalThreshold
  const yMax = Math.max(5, Math.ceil((refLine * 2) / 5) * 5)
  const clipped = peak.s > yMax

  // 版面：左轴标签 / 主图 / P0+P1 条带 / 整点标签
  const padL = width < 420 ? 30 : 36
  const padR = 10
  const padT = 16
  const showStripLabels = width >= 900
  const plotBottom = height - (showStripLabels ? 44 : withStrips ? 34 : 24)
  const plotW = Math.max(20, width - padL - padR)
  const plotH = Math.max(24, plotBottom - padT)

  const x = (t: number) => padL + ((t - vMin) / (vMax - vMin || 1)) * plotW
  const y = (score: number) =>
    padT + (1 - Math.min(score, yMax) / yMax) * plotH

  const path = view
    .map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(2)} ${y(p.s).toFixed(2)}`)
    .join(' ')
  const area =
    path +
    ` L${x(vMax).toFixed(2)} ${plotBottom}` +
    ` L${x(vMin).toFixed(2)} ${plotBottom} Z`

  // x 轴刻度：整点，不画短竖线
  const spanHours = (vMax - vMin) / HOUR
  const wideLabels = spanHours > 18
  const stepH = niceStep(spanHours, plotW, wideLabels)
  const tickMs = stepH * HOUR
  let tickAt = Math.ceil(vMin / tickMs) * tickMs
  const ticks: number[] = []
  for (let n = 0; tickAt <= vMax && n < 12; n++, tickAt += tickMs) ticks.push(tickAt)
  if (!ticks.length) ticks.push(vMin, vMax)

  const stripH = 6
  const p0RowY = plotBottom + 5
  const p1RowY = p0RowY + stripH + (showStripLabels ? 10 : 3)

  return {
    points,
    view,
    vMin,
    vMax,
    yMax,
    padL,
    padR,
    padT,
    plotW,
    plotH,
    plotBottom,
    ticks,
    wideLabels,
    peak,
    /** 峰值是否超出了 y 轴上限（画在顶边上并标注真实值） */
    clipped,
    path,
    area,
    p0RowY,
    p1RowY,
    stripH,
    showStripLabels,
    x,
    y,
  }
}

/**
 * 事件在条带上的矩形（x / 宽）。
 *
 * ⚠️ 超出可视范围的要被裁掉 —— 否则条带会画到轴外面。
 */
export function stripRect(
  geom: TrailGeometry,
  startTs: string,
  endTs: string | undefined,
): { x: number; width: number } | null {
  const start = Math.max(geom.vMin, toMs(startTs))
  const end = Math.min(geom.vMax, toMs(endTs ?? startTs))
  if (end < geom.vMin || start > geom.vMax) return null
  const ex = geom.x(start)
  const w = Math.max(3, geom.x(end) - ex)
  return { x: Math.min(ex, geom.x(geom.vMax) - w), width: w }
}
