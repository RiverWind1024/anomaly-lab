import { useMemo } from 'react'
import { List, Space, Tag } from 'antd'
import ReactECharts from 'echarts-for-react'
import { useSearchParams } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { cssVar, cssVarAlpha, invalidateCssVarCache, withAlpha } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import type { Badcase, Badcases } from '../../api/types'
import { useBadcases, useSummary } from './queries'

export interface BadcaseChartProps {
  data: Badcases
}

export interface BadcaseSeries {
  name?: string
  type?: string
  data?: unknown
  yAxisIndex?: number
  symbol?: string
  lineStyle?: { color?: string; width?: number; type?: string; opacity?: number }
  markArea?: { silent?: boolean; data?: unknown[] }
}

export interface BadcaseOption {
  series: Array<BadcaseSeries & Record<string, unknown>>
  xAxis?: unknown
  yAxis?: unknown
  dataZoom?: unknown[]
  legend?: { data?: string[]; top?: number; textStyle?: unknown; itemWidth?: number; itemHeight?: number }
  title?: { text?: string; top?: number; textStyle?: unknown }
}

/**
 * 把 Bad Case 的点索引压成**连续区间**。
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

/** Bad Case 类型的展示名与颜色。 */
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
 * 构造 Bad Case 详情图的 option。
 *
 * ⚠️ **必须用 `badcases[].indices` 真画出异常区间** —— 旧版写的是
 *    `markArea: data.badcases.length ? {} : undefined`，空对象 markArea 等于没画，
 *    异常区间从来没显示过（spec §8.2-B 要修掉的缺陷）。
 */
export function buildBadcaseOption(
  props: BadcaseChartProps,
  themeMode: 'dark' | 'light' = 'dark',
): BadcaseOption {
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

/** Bad Case 详情图。 */
export function BadcaseChart({ data }: BadcaseChartProps) {
  const themeMode = useThemeModeValue()
  const option = useMemo(() => buildBadcaseOption({ data }, themeMode), [data, themeMode])

  return (
    <div className="badcase-chart">
      <ReactECharts
        option={option as never}
        notMerge
        style={{ height: 420, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
      <Space size="small" wrap className="badcase-chart__legend">
        <Tag color="warning">橙色区间 = 误报（报了但没异常）</Tag>
        <Tag color="error">红色区间 = 漏报（有异常但没报）</Tag>
      </Space>
    </div>
  )
}

/**
 * Bad Case 页。
 *
 * 左栏序列列表（从 summary 的 rows 取），右栏详情图。
 *
 * ⚠️ 「该序列还没有检测结果」是**业务态**（`no_result`）——
 *    走 StateBoundary 的 bizState 路径显示空态，不是红色错误框。
 */
export function BadcasesPage() {
  const [params, setParams] = useSearchParams()
  const summary = useSummary()
  // 序列 ID 直接取自 URL —— 不另存一份 state，否则从评估页跳进来时状态不同步
  const seriesId = params.get('series_id') ?? undefined
  const badcases = useBadcases(seriesId)

  const select = (id: string) => {
    setParams({ series_id: id })
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">Bad Case</h1>
        <p className="page__subtitle">
          选一条序列看它的误报与漏报。区间由检测结果与真值比对得出。
        </p>
      </header>

      <div className="badcases-layout">
        <aside className="badcases-layout__list">
          <StateBoundary
            isLoading={summary.isPending}
            error={summary.error}
            data={summary.data}
            isEmpty={(data) => data.rows.length === 0}
            emptyTitle="暂无报告"
            emptyHint="先运行 evaluate"
          >
            {(data) => (
              <List
                size="small"
                dataSource={data.rows}
                renderItem={(row) => (
                  <List.Item
                    className={row.series_id === seriesId ? 'is-active' : undefined}
                    onClick={() => select(row.series_id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <span className="mono">{row.series_id}</span>
                  </List.Item>
                )}
              />
            )}
          </StateBoundary>
        </aside>

        <div className="badcases-layout__detail">
          <StateBoundary
            isLoading={badcases.isPending}
            error={badcases.error}
            data={badcases.data}
            bizTitles={{ no_result: '该序列还没有检测结果' }}
            emptyTitle="选一条序列"
            emptyHint="从左边列表里选一条"
          >
            {(data) => (
              <div className="badcase-detail">
                <BadcaseChart data={data} />
                <BadcaseList badcases={data.badcases} />
              </div>
            )}
          </StateBoundary>
        </div>
      </div>
    </div>
  )
}

/** Bad Case 明细列表：类型 + 分组 + 原因。 */
function BadcaseList({ badcases }: { badcases: Badcase[] }) {
  if (!badcases.length) {
    return <p className="muted">这条序列没有 Bad Case —— 检测结果与真值一致。</p>
  }
  return (
    <ul className="badcase-list">
      {badcases.map((item, index) => (
        <li key={index}>
          <Space size="small" wrap>
            <Tag color={item.kind === 'false_positive' ? 'warning' : 'error'}>
              {badcaseLabel(item.kind)}
            </Tag>
            <span className="mono muted">{item.group}</span>
            <span className="muted">
              {item.indices.length} 点（{item.indices[0]} ~ {item.indices[item.indices.length - 1]}）
            </span>
          </Space>
          <p className="badcase-list__reason">{item.reason}</p>
        </li>
      ))}
    </ul>
  )
}
