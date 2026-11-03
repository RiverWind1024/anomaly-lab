/**
 * 基线带的图表渲染（预览图与检测详情图共用）。
 *
 * ⚠️ **为什么不用 `stack` + `areaStyle`**：
 *    ECharts 的 stack 是**累加**的，且对负值的行为不可预测 ——
 *    实测（lower = −5.71、upper = 5.71）：
 *      - 底层铺 lower、上层传 `upper`         → 带画到 [0, 5.71]
 *      - 底层铺 lower、上层传 `upper − lower`  → 带画到 [5.71, 11.42]
 *    两种都不是 [lower, upper]。
 *
 *    所以改用 **custom series 画多边形**：`api.coord()` 把数据坐标转成像素，
 *    上界正着走、下界倒着走，闭合成一条带。**行为确定**，不依赖 stack 语义。
 */

import type { CustomSeriesOption } from 'echarts'

export interface BandPoint {
  lo: number
  hi: number
}

/** 一段连续区间：起点下标 + 该段的点。 */
export interface BandSegment {
  /** 段内第一个点在原始数组里的下标（用来还原 x 位置）。 */
  startIndex: number
  points: BandPoint[]
}

/**
 * 把 lower/upper 按缺点切成若干**连续段**。
 *
 * 缺点（null）处断开 —— 该处不画带，也不把两段连起来
 * （否则会画出一条横跨缺口的假带）。
 */
export function bandSegments(
  lower: (number | null)[] | null | undefined,
  upper: (number | null)[] | null | undefined,
): BandSegment[] {
  if (!lower || !upper || lower.length !== upper.length) return []
  const segments: BandSegment[] = []
  let points: BandPoint[] = []
  let startIndex = 0
  const flush = () => {
    if (points.length > 0) segments.push({ startIndex, points })
    points = []
  }
  for (let i = 0; i < lower.length; i += 1) {
    const lo = lower[i]
    const hi = upper[i]
    if (lo == null || hi == null || hi < lo) {
      flush()
      continue
    }
    if (points.length === 0) startIndex = i
    points.push({ lo, hi })
  }
  flush()
  return segments
}

export interface BandSeriesOptions {
  lower: (number | null)[] | null | undefined
  upper: (number | null)[] | null | undefined
  /** 图例里显示的名字。 */
  name: string
  /** 带填充色。 */
  color: string
  /** 填充不透明度。 */
  opacity?: number
  /** 层级，越小越靠后。 */
  z?: number
}

/**
 * 构造画基线带的 custom series。
 *
 * 一次渲染产出**若干个多边形**（每段连续区间一个），
 * 不依赖 `stack`，不受负值影响。
 */
export function buildBandSeries(options: BandSeriesOptions): CustomSeriesOption {
  const { lower, upper, name, color, opacity = 0.12, z = 0 } = options
  // 段在构造期算好 —— renderItem 里拿不到原始数组
  const segments = bandSegments(lower, upper)
  return {
    name,
    type: 'custom',
    silent: true,
    z,
    // ⚠️ 图例 marker 取 itemStyle.color —— 不给就用 ECharts 默认调色板，
    //    颜色会跟带本身对不上
    itemStyle: { color },
    data: [[0]],
    renderItem: (_params, api) => {
      const children = segments.map((segment) => {
        const top: number[][] = []
        const bottom: number[][] = []
        segment.points.forEach((point, index) => {
          const xIndex = segment.startIndex + index
          top.push(api.coord([xIndex, point.hi]))
          bottom.push(api.coord([xIndex, point.lo]))
        })
        const points = [...top, ...bottom.reverse()]
        return {
          type: 'polygon',
          shape: { points },
          style: { fill: color, opacity },
        }
      })
      return { type: 'group', children }
    },
  } as CustomSeriesOption
}
