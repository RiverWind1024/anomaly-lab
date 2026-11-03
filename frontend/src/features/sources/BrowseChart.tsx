import ReactECharts from 'echarts-for-react'
import { Empty } from 'antd'
import { cssVar, cssVarAlpha, invalidateCssVarCache } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import { seriesColor, seriesDashed } from '../../lib/palette'
import type { SourceQueryColumn } from '../../api/types'

export interface BrowseChartProps {
  /** 浏览结果里的行（数组，列名在 columns 里）。 */
  rows: unknown[][]
  /** 浏览结果的列结构。 */
  columns: SourceQueryColumn[]
  /** 哪一列是时间列 / 值列 / 分组列。 */
  roles: {
    time_column?: string
    value_column?: string
    group_column?: string
  }
  /**
   * 时间轴坐标（epoch 毫秒）—— 后端用**与指标运行时同一份**逻辑解析。
   *
   * ⚠️ `null` = 没有时间列 → 不画图。
   * ⚠️ 元素里的 `null` = 那一行时间解析不出来 → 跳过该点。
   */
  timeValues: (number | null)[] | null
}

/** 一条线（一组）。 */
export interface BrowseSeries {
  name: string
  /** `[时间毫秒, 值]` —— 值为 null 是断点。 */
  points: Array<[number, number | null]>
}

/** option 里我们关心的部分（单测要断言的字段）。 */
export interface BrowseOption {
  series: Array<BrowseSeriesOption & Record<string, unknown>>
  xAxis?: unknown
  yAxis?: unknown
  tooltip?: unknown
  legend?: unknown
  dataZoom?: unknown[]
}

/** 单测要断言的字段。 */
export interface BrowseSeriesOption {
  name?: string
  type?: string
  data?: unknown
  symbol?: string
  symbolSize?: number
  connectNulls?: boolean
  lineStyle?: { color?: string; width?: number; type?: string }
  itemStyle?: { color?: string }
}

/** 为什么画不出图 —— 给用户一句能照着做的话。 */
export type BrowseChartReason =
  | 'no-time-column'
  | 'no-value-column'
  | 'no-rows'
  | 'no-parseable-time'

/**
 * 从浏览结果里抽出要画的线。
 *
 * 抽成纯函数是为了能单测 —— 「时间解析不出来就跳过」「分组怎么拆」
 * 这些行为应该可验证，而不是只能肉眼看图。
 *
 * ⚠️ **按角色取列**，不按列名猜 —— 角色是用户在列头下拉里定的。
 */
export function extractBrowseSeries(props: BrowseChartProps): BrowseSeries[] {
  const { rows, columns, roles, timeValues } = props
  if (!timeValues) return []

  const timeIndex = roles.time_column
    ? columns.findIndex((column) => column.name === roles.time_column)
    : -1
  const valueIndex = roles.value_column
    ? columns.findIndex((column) => column.name === roles.value_column)
    : -1
  const groupIndex = roles.group_column
    ? columns.findIndex((column) => column.name === roles.group_column)
    : -1
  if (timeIndex < 0 || valueIndex < 0) return []

  const pointsByGroup = new Map<string, Array<[number, number | null]>>()
  rows.forEach((row, index) => {
    const stamp = timeValues[index]
    // ⚠️ 时间解析不出来的行**跳过** —— 拿 0 顶替会画到 1970 年，
    //    看着像「数据都在 1970 年」，比空白更误导。
    if (stamp == null || !Number.isFinite(stamp)) return
    const raw = row[valueIndex]
    const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : null
    const group =
      groupIndex >= 0
        ? String(row[groupIndex] ?? 'null')
        : (roles.value_column ?? '值')
    const points = pointsByGroup.get(group)
    if (points) points.push([stamp, value])
    else pointsByGroup.set(group, [[stamp, value]])
  })

  // ⚠️ Map 的插入顺序 = 首次出现的顺序 —— 图例的顺序跟着数据走，
  //    每次重跑都一样（不按字典序排，避免同一条线换位置）。
  return [...pointsByGroup.entries()].map(([name, points]) => ({ name, points }))
}

/**
 * 画不出图的原因。
 *
 * ⚠️ 区分「没有时间列」与「有时间列但一个都解析不出来」——
 *    前者要用户去指派，后者是数据本身的问题，话不能一样。
 */
export function browseChartReason(props: BrowseChartProps): BrowseChartReason | null {
  const { rows, roles, timeValues } = props
  if (!roles.time_column) return 'no-time-column'
  if (!roles.value_column) return 'no-value-column'
  if (rows.length === 0) return 'no-rows'
  if (!timeValues || extractBrowseSeries(props).length === 0) return 'no-parseable-time'
  return null
}

/**
 * 把数据范围收成「好看」的边界（1 位有效数字的台阶）。
 *
 * ⚠️ 为什么不用 `min: 'dataMin'` —— 那会把 `12.0746815396624` 这种
 *    原始值直接当刻度标签，一眼看去全是数字噪声。
 * ⚠️ 为什么不用 `scale: true` —— 它只是「不强制含 0」，
 *    ECharts 随后的 nice 取整仍会把 min 拉回 0（间隔取 20 就正好落在 0）。
 *    于是 12~92 的数据被画在 0~100 里，纵向白白浪费 12%。
 *
 * ⚠️ min **向下**取、max **向上**取 —— 宁可多留一点空白，
 *    也不能把数据切在轴外（看着像数据丢了）。
 */
function niceBounds(min: number, max: number): { min: number; max: number } {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min, max }
  if (min === max) return { min: min - 1, max: max + 1 }
  const step = (value: number, round: 'floor' | 'ceil') => {
    if (value === 0) return 0
    const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(value))))
    const scaled = value / mag
    return (round === 'floor' ? Math.floor(scaled) : Math.ceil(scaled)) * mag
  }
  return { min: step(min, 'floor'), max: step(max, 'ceil') }
}

/**
 * 构造浏览时序图的 ECharts option。
 *
 * ⚠️ 颜色全部从 tokens.css 的变量读出实际值（ECharts 不吃 CSS 变量）。
 *
 * @param themeMode 当前主题 —— 变了就清掉色值缓存，让下次读到新主题的颜色
 */
export function buildBrowseOption(
  props: BrowseChartProps,
  themeMode: 'dark' | 'light' = 'dark',
): BrowseOption {
  // 主题变了就清缓存 —— 否则读到的是上一套主题的颜色。
  invalidateCssVarCache(themeMode)
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')

  const series: BrowseOption['series'] = extractBrowseSeries(props).map(
    (item, index) => {
      const color = seriesColor(index)
      // ⚠️ 超出色板长度的序列用**虚线** —— 颜色会循环，
      //    不同线型才分得清哪条是哪条（见 palette.seriesDashed）。
      const dashed = seriesDashed(index)
      return {
        name: item.name,
        type: 'line',
        // ⚠️ 真时间轴 → 数据点是 `[x, y]` 对，不是按序号的数组
        data: item.points,
        // ⚠️ 单点时 `symbol: 'none'` 会让它**隐形** —— 少于两个点就显示圆点
        symbol: item.points.length < 2 ? 'circle' : 'none',
        symbolSize: 6,
        // ⚠️ 缺点必须断线 —— ECharts 默认 connectNulls:false，别打开
        connectNulls: false,
        lineStyle: { color, width: 1.6, type: dashed ? 'dashed' : 'solid' },
        itemStyle: { color },
        z: 3,
      }
    },
  )

  // ⚠️ y 轴范围贴着数据走（不从 0 起）—— 边界自己算，见 niceBounds 的说明
  const values = series.flatMap((item) =>
    (item.data as Array<[number, number | null]>).map((pair) => pair[1]),
  )
  const numbers = values.filter((value): value is number => value !== null)
  const bounds =
    numbers.length > 0
      ? niceBounds(Math.min(...numbers), Math.max(...numbers))
      : { min: 0, max: 1 }

  return {
    series,
    legend: {
      top: 0,
      textStyle: { color: textTertiary, fontSize: 11 },
      itemWidth: 14,
      itemHeight: 8,
    },
    // ⚠️ **真时间轴**（不是 category）—— 缺采造成的不等间隔能正确表达。
    //    类别轴会把空档压掉，看起来像采样很密。
    xAxis: {
      type: 'time',
      axisLabel: { color: textTertiary, fontSize: 11 },
      axisLine: { lineStyle: { color: border } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      // ⚠️ **不从 0 起**（Grafana 的做法）—— 值都在 12~92 时，
      //    从 0 起会把曲线压扁。边界自己算，见 niceBounds。
      min: bounds.min,
      max: bounds.max,
      axisLabel: { color: textTertiary, fontSize: 11 },
      axisLine: { lineStyle: { color: border } },
      splitLine: { lineStyle: { color: border, opacity: 0.45 } },
    },
    tooltip: {
      // ⚠️ 悬停显示**该时刻所有系列**的值（Grafana 的行为）
      trigger: 'axis',
      axisPointer: { type: 'cross' },
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

/** 各状态对应的话 —— 都要给出**下一步该做什么**，不是只说「没有数据」。 */
const REASON_TEXT: Record<BrowseChartReason, string> = {
  'no-time-column': '把某一列指派为「时间列」，这里就能画出时序图。',
  'no-value-column': '把某一列指派为「值列」，这里就能画出时序图。',
  'no-rows': '这次查询没有取到数据 —— 换个时间范围或检查 SQL。',
  'no-parseable-time': '时间列一个值都解析不出来 —— 检查「时间格式」与「源时区」是否对得上源数据。',
}

/**
 * 浏览结果的时序图。
 *
 * ⚠️ 画不出的时候**说清楚为什么、接下来做什么** ——
 *    一个空白的框会让人以为「这个源没数据」。
 */
export function BrowseChart(props: BrowseChartProps) {
  // 订阅主题 —— ECharts 不认 CSS 变量，主题变了必须重建 option 才能换色
  const themeMode = useThemeModeValue()
  const reason = browseChartReason(props)
  // themeMode 进依赖：它变了就重建 option（颜色是运行时从 CSS 变量读的）
  const option = buildBrowseOption(props, themeMode)

  if (reason) {
    return (
      <div className="browse-chart">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span className="muted">
              {reason === 'no-time-column' || reason === 'no-value-column'
                ? '还差一列就能画图 —— '
                : ''}
              {REASON_TEXT[reason]}
            </span>
          }
        />
      </div>
    )
  }

  return (
    <div className="browse-chart">
      <ReactECharts
        option={option as never}
        notMerge
        style={{ height: 340, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
      <p className="muted browse-chart__note">
        提示：滚轮/拖拽可缩放；悬停看该时刻各系列的值。
      </p>
    </div>
  )
}
