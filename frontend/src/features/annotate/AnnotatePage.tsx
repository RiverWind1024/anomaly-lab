import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Select, Space, Tag, message } from 'antd'
import ReactECharts from 'echarts-for-react'
import type { ECharts } from 'echarts'
import { StateBoundary } from '../../components/StateBoundary'
import { cssVar, cssVarAlpha, invalidateCssVarCache } from '../../theme/cssVar'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import type { Annotation, SeriesValues } from '../../api/types'
import { useSeries } from '../series/queries'
import { fmtDateTime } from '../../lib/format'
import {
  useAnnotations,
  useProductionSamples,
  useRunSeriesDetail,
  useSaveAnnotations,
  useSeriesValues,
} from './queries'

/**
 * 异常类型。固定 6 种（照搬旧 `annotate.js:61` 的提示文案）。
 *
 * ⚠️ 旧版用 `prompt` 弹窗让用户手输 —— 现在改成下拉，
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

  const textTertiary = cssVar('--text-tertiary', '#7f7f8b')
  const border = cssVar('--border-subtle', '#26262b')
  // ⚠️ 主数据元素（信号本身）用**这一个数据色** —— 全用中性色就成了没有身份的 kit
  const chart = cssVar('--chart', '#6da8e3')

  // ⚠️ 标注存的是**时间戳**，图上的 x 轴是**下标** —— 这里要换算回去。
  //    换算不出来的（序列变了、时间对不上）直接跳过：画一个错位的区间比不画更糟。
  const areas = annotations.flatMap((item) => {
    const start = data.timestamps.indexOf(item.start)
    const end = data.timestamps.indexOf(item.end)
    if (start < 0 || end < 0) return []
    return [
      [
        { xAxis: start, itemStyle: { color: cssVarAlpha('--status-p0', 0.22, 'rgba(239,68,68,0.22)') } },
        { xAxis: end },
      ],
    ]
  })

  return {
    series: [
      {
        name: '数值',
        type: 'line',
        data: data.values,
        symbol: 'none',
        lineStyle: { color: chart, width: 1.6 },
        markArea: { silent: true, data: areas },
      },
    ],
    xAxis: {
      type: 'category',
      data: data.timestamps.map((ts) => fmtDateTime(ts)),
      boundaryGap: false,
      axisLabel: { color: textTertiary, fontSize: 11 },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: textTertiary, fontSize: 11 },
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
        textStyle: { color: textTertiary, fontSize: 11 },
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
 *       选异常类型（**下拉，不是 prompt 弹窗**）→ 保存。
 *
 * ⚠️ **两类序列**：
 *   - 基准集（合成序列）—— 真值本来就有，标注是补充；
 *   - 生产检测记录 —— **真值只能靠人工标**，这是评估生产效果的唯一途径。
 *     它的波形直接读那次 run 的产物，跟当时跑的那份完全一致。
 */
export function AnnotatePage() {
  const series = useSeries()
  const production = useProductionSamples()
  const [target, setTarget] = useState<{ seriesId: string; runId?: number } | undefined>(
    undefined,
  )
  const [pending, setPending] = useState<{ start: number; end: number } | null>(null)
  const [anomalyType, setAnomalyType] = useState<string>('spike')

  const seriesId = target?.seriesId
  const runId = target?.runId

  // ⚠️ 两套取数：基准集读数据集，生产记录读那次 run 的产物。
  const datasetValues = useSeriesValues(runId ? undefined : seriesId)
  const runValues = useRunSeriesDetail(runId, runId ? seriesId : undefined)
  const values = runId ? runValues : datasetValues

  const annotations = useAnnotations(seriesId)
  const save = useSaveAnnotations(seriesId, runId)

  // 默认选第一条序列（旧版行为）
  const seriesList = series.data ?? []
  const productionList = production.data ?? []
  useEffect(() => {
    if (!target && seriesList.length > 0) {
      setTarget({ seriesId: seriesList[0].series_id })
    }
  }, [target, seriesList])

  const handleBrush = (start: number, end: number) => {
    setPending({ start, end })
  }

  const handleSave = async () => {
    if (!pending || !seriesId) return
    const stamps = values.data?.timestamps ?? []
    // ⚠️ 存**时间戳**而不是下标 —— 序列滚动后下标会指向别的时刻。
    const start = stamps[pending.start]
    const end = stamps[pending.end]
    if (!start || !end) {
      message.warning('选中的区间超出序列范围')
      return
    }
    save.mutate(
      [
        {
          start,
          end,
          type: anomalyType,
          // ⚠️ **采样率跟着标注一起存** —— 采样率后来变了，
          //    这条标注仍按它当初的权重反算总体。
          ...(currentSample
            ? { rate: currentSample.rate, layer_size: currentSample.layer_size }
            : {}),
        },
        // ⚠️ **画了标注 = 看了整条波形** → 顺带声明这次运行核对过。
        //    没有这条声明，评估只能把其余时段当正常 ——
        //    窗口里几十个没看过的告警点会**凭空变成误报**。
        ...(runId
          ? [
              {
                type: 'reviewed',
                ...(currentSample
                  ? { rate: currentSample.rate, layer_size: currentSample.layer_size }
                  : {}),
              },
            ]
          : []),
      ],
      {
        onSuccess: () => {
          setPending(null)
        },
      },
    )
  }

  /** 「这条记录正常」—— 不画区间，一键确认整个窗口没有异常。
   *
   *  ⚠️ 这是**负样本标签** —— 没有它，漏报（FN）永远测不出来。
   */
  const handleMarkNormal = () => {
    if (!seriesId) return
    save.mutate(
      [
        {
          type: 'reviewed',
          ...(currentSample
            ? { rate: currentSample.rate, layer_size: currentSample.layer_size }
            : {}),
        },
      ],
      {
        onSuccess: () => {
          message.success('已记为「这条记录正常」')
        },
      },
    )
  }

  // ⚠️ 下拉分两组 —— 基准集与生产记录是两回事，混在一列里没法找。
  const seriesOptions = [
    {
      label: '基准集（合成序列）',
      options: seriesList.map((item) => ({
        value: `dataset:${item.series_id}`,
        label: `${item.series_id} (${item.metric_class}, n=${item.n})`,
      })),
    },
    {
      label: '生产检测记录',
      options: productionList.map((item) => ({
        value: `run:${item.run_id}:${item.series_id}`,
        // ⚠️ **检出结果（正常/异常）要写出来** —— 两层的采样率不同，
        //    标注任务也不同：异常记录查误报，正常记录查漏报。
        label:
          `${item.series_id} · run ${item.run_id} · ` +
          `${item.outcome_label} · 告警 ${item.n_alerts}` +
          (item.n_annotations > 0 ? ' · 已标' : ' · 待标'),
      })),
    },
  ]

  /** 下拉的 value → 目标（序列 + 可选的 run）。 */
  const parseTarget = (value: string) => {
    if (value.startsWith('run:')) {
      const [, runId, ...rest] = value.split(':')
      return { runId: Number(runId), seriesId: rest.join(':') }
    }
    return { seriesId: value.replace(/^dataset:/, '') }
  }

  const targetValue = target
    ? target.runId
      ? `run:${target.runId}:${target.seriesId}`
      : `dataset:${target.seriesId}`
    : undefined

  const currentSample = productionList.find(
    (item) => item.run_id === runId && item.series_id === seriesId,
  )

  return (
    <div className="page">
      <header className="titlebar">
        <h1>标注</h1>
      </header>

      <div className="runs-view__bar">
        <div className="runs-view">
          <label className="runs-view__label" htmlFor="annotate-series">
            序列
          </label>
          <Select
            id="annotate-series"
            className="runs-view__select"
            loading={series.isPending || production.isPending}
            value={targetValue}
            placeholder="选择序列"
            options={seriesOptions}
            onChange={(value) => {
              setTarget(parseTarget(value as string))
              setPending(null)
            }}
            showSearch
            optionFilterProp="label"
            style={{ minWidth: 520 }}
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
                {/* ⚠️ 「核对过」不是异常标注 —— 计数时排除掉，否则会虚高。 */}
                <Tag>
                  {(annotations.data?.intervals ?? []).filter(
                    (item) => item.type !== 'reviewed',
                  ).length}{' '}
                  条异常标注
                </Tag>
                {currentSample ? (
                  <>
                    <Tag>{currentSample.source_name} / {currentSample.metric_name}</Tag>
                    <Tag>run {currentSample.run_id}</Tag>
                    <Tag
                      color={currentSample.outcome === 'alert' ? 'volcano' : 'default'}
                    >
                      {currentSample.outcome_label}
                    </Tag>
                    <Tag>{currentSample.detector} · 告警 {currentSample.n_alerts}</Tag>
                    <Tag color={currentSample.reviewed ? 'green' : 'default'}>
                      {currentSample.reviewed ? '已核对' : '待核对'}
                    </Tag>
                  </>
                ) : null}
              </Space>
              {runId ? (
                <Button size="small" loading={save.isPending} onClick={handleMarkNormal}>
                  这条记录正常
                </Button>
              ) : null}
            </div>

            {save.error instanceof Error && (
              <Alert type="error" showIcon message={save.error.message} />
            )}

            {/*
              ⚠️ **标注按序列存，不按运行** —— 用户选一次运行只是为了看波形；
                 标出来的区间会复用给所有覆盖该时段的检测记录。
                 不说清楚的话，用户会以为自己只标了这一次运行。
            */}
            {runId ? (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="标注按序列保存，覆盖所有包含该时段的检测记录"
                description="不用为每次运行重复标同一段异常 —— 一次标注，所有覆盖它的运行都复用。这条波形核对过就点「这条记录正常」；评估只在核对过的时间段里计分。"
              />
            ) : null}

            <AnnotateChart
              data={data}
              annotations={annotations.data?.intervals ?? []}
              onBrush={handleBrush}
            />

            {pending && (
              <div className="annotate-page__actions">
                <Space wrap>
                  <span>
                    已选区间：
                    <span className="mono">
                      {fmtDateTime(values.data?.timestamps[pending.start] ?? null)} ~{' '}
                      {fmtDateTime(values.data?.timestamps[pending.end] ?? null)}
                    </span>
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
