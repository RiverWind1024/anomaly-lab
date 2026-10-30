import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Select, Space, Tag } from 'antd'
import ReactECharts from 'echarts-for-react'
import type { ECharts } from 'echarts'
import { StateBoundary } from '../../components/StateBoundary'
import { cssVar, cssVarAlpha, invalidateCssVarCache } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import type { Annotation, SeriesValues } from '../../api/types'
import { useSeries } from '../series/queries'
import {
  useAnnotations,
  useSaveAnnotations,
  useSeriesValues,
} from './queries'

/**
 * 异常类型。固定 6 种（照搬旧 `annotate.js:61` 的提示文案）。
 *
 * ⚠️ 旧版用 `prompt()` 让用户手输 —— 现在改成下拉，
 *    避免输错导致标注静默失效（spec §8.2-B）。
 */
export const ANOMALY_TYPES = [
  { value: 'spike', label: 'spike（尖峰）' },
  { value: 'contextual', label: 'contextual（上下文异常）' },
  { value: 'drift', label: 'drift（漂移）' },
  { value: 'freq_shift', label: 'freq_shift（频率变化）' },
  { value: 'variance_shift', label: 'variance_shift（方差变化）' },
  { value: 'flatline', label: 'flatline（平线）' },
] as const

export interface AnnotateChartProps {
  data: SeriesValues
  annotations: Annotation[]
  /** 刷选结束后回调（区间是**索引**，不是时间戳） */
  onBrush: (start: number, end: number) => void
}

export interface AnnotateSeries {
  name?: string
  type?: string
  data?: unknown
  markArea?: { silent?: boolean; data?: unknown[] }
  symbol?: string
  lineStyle?: { color?: string; width?: number }
}

export interface AnnotateOption {
  series: Array<AnnotateSeries & Record<string, unknown>>
  xAxis?: unknown
  yAxis?: unknown
  dataZoom?: unknown[]
  brush?: { xAxisIndex?: number; brushMode?: string; throttleType?: string; throttleDelay?: number }
  toolbox?: { feature?: Record<string, unknown> }
}

/**
 * 构造标注图的 option。
 *
 * 已有标注画成 markArea（红色半透明区间）—— 旧版也是这么画的。
 */
export function buildAnnotateOption(
  props: AnnotateChartProps,
  themeMode: 'dark' | 'light' = 'dark',
): AnnotateOption {
  const { data, annotations } = props
  invalidateCssVarCache(themeMode)

  const textPrimary = cssVar('--text-primary', '#fafafa')
  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')

  const areas = annotations.map((item) => [
    { xAxis: item.start, itemStyle: { color: cssVarAlpha('--status-p0', 0.22, 'rgba(239,68,68,0.22)') } },
    { xAxis: item.end },
  ])

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
    ],
    xAxis: {
      type: 'category',
      data: data.timestamps,
      boundaryGap: false,
      axisLabel: { color: textTertiary, fontSize: 10 },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: textTertiary, fontSize: 10 },
      splitLine: { lineStyle: { color: border, opacity: 0.45 } },
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
        textStyle: { color: textTertiary, fontSize: 10 },
      },
    ],
    // 刷选 —— 只在 x 轴上，单选
    brush: {
      xAxisIndex: 0,
      brushMode: 'single',
      throttleType: 'debounce',
      throttleDelay: 300,
    },
    toolbox: { feature: { restore: {} } },
  }
}

/** 标注波形图。 */
function AnnotateChart({ data, annotations, onBrush }: AnnotateChartProps) {
  const themeMode = useThemeModeValue()
  const option = useMemo(
    () => buildAnnotateOption({ data, annotations, onBrush }, themeMode),
    [data, annotations, onBrush, themeMode],
  )

  const chartRef = useRef<ECharts | null>(null)
  const onBrushRef = useRef(onBrush)
  onBrushRef.current = onBrush

  // brushSelected 事件：拿到选区的索引范围
  const handleBrushSelected = useCallback((params: unknown) => {
    const batch = (params as { batch?: Array<{ selected?: Array<{ coordRange?: number[] }> }> })
      ?.batch
    const selected = batch?.[0]?.selected
    if (!selected || !selected.length) return
    const range = selected[0].coordRange
    if (!range || range.length < 2) return
    const start = Math.min(...range)
    const end = Math.max(...range)
    onBrushRef.current(start, end)
  }, [])

  return (
    <div className="annotate-chart">
      <ReactECharts
        option={option as never}
        notMerge
        style={{ height: 420, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        onChartReady={(instance) => {
          chartRef.current = instance
        }}
        onEvents={{ brushSelected: handleBrushSelected }}
      />
      <p className="muted">
        在图上按住拖动即可刷选区间；滚轮/下方滑块可缩放。红色区间是已保存的标注。
      </p>
    </div>
  )
}

/**
 * 标注页。
 *
 * 流程：选序列 → 拉波形 → 拉已有标注 → 画波形 → 刷选区间 →
 *       选异常类型（**下拉，不是 prompt()**）→ 保存。
 */
export function AnnotatePage() {
  const series = useSeries()
  const [seriesId, setSeriesId] = useState<string | undefined>(undefined)
  const [pending, setPending] = useState<{ start: number; end: number } | null>(null)
  const [anomalyType, setAnomalyType] = useState<string>('spike')

  const values = useSeriesValues(seriesId)
  const annotations = useAnnotations(seriesId)
  const save = useSaveAnnotations(seriesId)

  // 默认选第一条序列（旧版行为）
  const seriesList = series.data ?? []
  useEffect(() => {
    if (!seriesId && seriesList.length > 0) setSeriesId(seriesList[0].series_id)
  }, [seriesId, seriesList])

  const handleBrush = (start: number, end: number) => {
    setPending({ start, end })
  }

  const handleSave = async () => {
    if (!pending || !seriesId) return
    save.mutate(
      [{ start: pending.start, end: pending.end, type: anomalyType }],
      {
        onSuccess: () => {
          setPending(null)
        },
      },
    )
  }

  const seriesOptions = seriesList.map((item) => ({
    value: item.series_id,
    label: `${item.series_id} (${item.metric_class}, n=${item.n})`,
  }))

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">标注</h1>
        <p className="page__subtitle">
          在波形上刷选异常区间，选择异常类型后保存。标注存成 JSONL，供评估与调参使用。
        </p>
      </header>

      <div className="runs-view__bar">
        <div className="runs-view">
          <label className="runs-view__label" htmlFor="annotate-series">
            序列
          </label>
          <Select
            id="annotate-series"
            className="runs-view__select"
            loading={series.isPending}
            value={seriesId}
            placeholder="选择序列"
            options={seriesOptions}
            onChange={(value) => {
              setSeriesId(value as string)
              setPending(null)
            }}
            showSearch
            optionFilterProp="label"
            style={{ minWidth: 360 }}
          />
        </div>
      </div>

      <StateBoundary
        isLoading={values.isPending || series.isPending}
        error={values.error ?? series.error}
        data={values.data}
        isEmpty={(data) => data.values.length === 0}
        emptyTitle="这条序列没有数据"
        emptyHint="换一个序列看看"
      >
        {(data) => (
          <div className="annotate-page">
            <div className="annotate-page__meta">
              <Space size="small" wrap>
                <Tag>{data.series_id}</Tag>
                <Tag>{data.timestamps.length} 点</Tag>
                <Tag>{annotations.data?.intervals.length ?? 0} 条标注</Tag>
              </Space>
            </div>

            {save.error instanceof Error && (
              <Alert type="error" showIcon message={save.error.message} />
            )}

            <AnnotateChart
              data={data}
              annotations={annotations.data?.intervals ?? []}
              onBrush={handleBrush}
            />

            {pending && (
              <div className="annotate-page__actions">
                <Space wrap>
                  <span>
                    已选区间：索引 {pending.start} ~ {pending.end}
                  </span>
                  <Select
                    value={anomalyType}
                    onChange={setAnomalyType}
                    options={ANOMALY_TYPES.map((t) => ({ value: t.value, label: t.label }))}
                    style={{ width: 220 }}
                  />
                  <Button type="primary" loading={save.isPending} onClick={handleSave}>
                    保存标注
                  </Button>
                  <Button onClick={() => setPending(null)}>取消</Button>
                </Space>
              </div>
            )}
          </div>
        )}
      </StateBoundary>
    </div>
  )
}
