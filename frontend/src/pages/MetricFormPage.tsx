import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Form, Space } from 'antd'
import { useCatalog } from '../features/jobs/queries'
import { createMetric, updateMetric } from '../api/platform'
import {
  DEFAULT_METRIC_QUERY,
  MetricFormFields,
  buildMetricPayload,
  type MetricFormValues,
} from '../features/metrics/MetricFormFields'
import { MetricChartPanel } from '../features/metrics/MetricChartPanel'
import {
  PREVIEW_STORAGE_KEY,
  readPreviewPayload,
} from '../features/metrics/previewBridge'

/** 没有任何告警任务时，预览用的默认窗口点数。 */
const DEFAULT_WINDOW_POINTS = 60

/**
 * 指标配置页 —— 新增与编辑共用。
 *
 * ⚠️ **为什么是独立页面而不是弹窗**：
 *    指标配置要写 SQL、要选列、要预览取回来的数据 ——
 *    弹窗塞不下这些，预览还要开新标签页（弹窗会跟着消失）。
 *    独立页面能给「预览数据」腾出位置。
 *
 * ⚠️ URL：
 *    - 新增：`/metrics/new?source_id=3`（从哪个数据源来）
 *    - 编辑：`/metrics/5/edit`
 */
export function MetricFormPage() {
  const [params] = useSearchParams()
  const routeParams = useParams<{ metricId: string }>()
  const navigate = useNavigate()
  const catalog = useCatalog()
  const qc = useQueryClient()
  const [form] = Form.useForm<MetricFormValues>()

  const metricId = routeParams.metricId ? Number(routeParams.metricId) : undefined
  const isEditing = metricId !== undefined
  const sourceIdParam = params.get('source_id')

  const metric = useMemo(
    () => catalog.data?.metrics.find((item) => item.id === metricId),
    [catalog.data?.metrics, metricId],
  )
  const source = useMemo(
    () =>
      catalog.data?.sources.find(
        (item) => item.id === metric?.source_id || item.id === Number(sourceIdParam),
      ),
    [catalog.data?.sources, metric?.source_id, sourceIdParam],
  )

  /**
   * 预览页带回来的取数配置 —— 用来预填表单。
   *
   * ⚠️ 用 state 而不是直接写表单 —— 表单的 `initialValues` 只在挂载时生效，
   *    而预览页是**回来之后**才把配置送到的。
   */
  const [prefill, setPrefill] = useState<Partial<MetricFormValues> | null>(null)

  /**
   * 接住预览页带回来的配置。
   *
   * ⚠️ 预览页开在新标签页里，用 localStorage 回传 ——
   *    storage 事件只在**别的**标签页触发，正好是这里要的。
   */
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== PREVIEW_STORAGE_KEY) return
      const payload = readPreviewPayload(event.newValue)
      // ⚠️ 消费掉 —— 别让同一份配置反复填表单
      window.localStorage.removeItem(PREVIEW_STORAGE_KEY)
      if (!payload) return
      setPrefill({
        // ⚠️ 只有 SQL 里带 $timefilter 才预填 query ——
        //    指标要求恰好一个 $timefilter，预填非法 SQL 会让用户白填一遍
        ...(payload.sql.includes('$timefilter') ? { query: payload.sql } : {}),
        time_column: payload.time_column ?? '',
        value_column: payload.value_column ?? '',
        group_column: payload.group_column ?? '',
        time_format: payload.time_format ?? 'iso_utc',
      })
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  /**
   * 表单初值 —— 编辑态取指标，新增态给默认值。
   *
   * ⚠️ 新增态的 `source_id` **不依赖 catalog**（来自 URL），
   *    所以新增时能立刻灌 —— 不用等 catalog 回来，
   *    免得用户已经敲的字被异步数据冲掉。
   */
  const initialValues = useMemo<Partial<MetricFormValues>>(
    () =>
      metric
        ? {
            source_id: metric.source_id,
            name: metric.name,
            query: metric.query,
            time_column: metric.time_column,
            value_column: metric.value_column,
            group_column: metric.group_column ?? '',
            time_format: metric.time_format,
            source_timezone: metric.source_timezone,
            missing_policy: metric.missing_policy,
            freq: metric.freq,
          }
        : {
            source_id: sourceIdParam ? Number(sourceIdParam) : undefined,
            name: '',
            group_column: '',
            time_column: 'ts',
            value_column: 'value',
            time_format: 'iso_utc',
            source_timezone: 'UTC',
            missing_policy: 'drop',
            freq: '5min',
            query: DEFAULT_METRIC_QUERY,
          },
    [metric, sourceIdParam],
  )

  /**
   * 把初值灌回表单 —— **只灌一次**。
   *
   * ⚠️ 必须「只灌一次」：catalog 是异步到的，
   *    每次渲染都灌的话，用户敲的字会被冲掉。
   */
  const seeded = useRef(false)
  useEffect(() => {
    if (seeded.current) return
    // 编辑态要等指标本身 —— 灌早了会把默认值盖上去
    if (isEditing && !metric) return
    form.setFieldsValue(initialValues)
    seeded.current = true
  }, [form, initialValues, isEditing, metric])

  /**
   * 预览页带回的配置 —— 覆盖初值。
   *
   * ⚠️ 单独一个 effect：预填是**后来**到的（用户去预览页转一圈回来），
   *    它必须比初值**晚**生效。
   */
  useEffect(() => {
    if (!prefill) return
    form.setFieldsValue(prefill)
    setPrefill(null)
  }, [form, prefill])

  /**
   * 表单当前值 —— 预览用它（**不是已保存的指标**）。
   *
   * ⚠️ 页内预览的价值就在于「改 SQL 立刻看到效果」——
   *    用已保存的值预览，用户改了半天看不到变化。
   */
  const watched = Form.useWatch([], form)

  /**
   * 预览的窗口点数 —— 取该指标正在用的告警任务的设置。
   *
   * ⚠️ **指标本身没有「取多少数据」的字段** —— 那是告警任务的配置。
   *    用户在这里会疑惑「为什么只这么多点」，所以下面要写清楚去哪改。
   */
  const metricJob = useMemo(
    () => catalog.data?.jobs.find((item) => item.metric_id === metricId),
    [catalog.data?.jobs, metricId],
  )
  const windowPoints = metricJob?.window_points ?? DEFAULT_WINDOW_POINTS

  /** 预览用的取数配置 —— 全取表单当前值。 */
  const previewConfig = useMemo(
    () => ({
      query: watched?.query ?? metric?.query ?? '',
      time_column: watched?.time_column ?? metric?.time_column ?? '',
      value_column: watched?.value_column ?? metric?.value_column ?? '',
      group_column: watched?.group_column ?? metric?.group_column ?? '',
      time_format: watched?.time_format ?? metric?.time_format ?? 'iso_utc',
      source_timezone: watched?.source_timezone ?? metric?.source_timezone ?? 'UTC',
    }),
    [watched, metric],
  )
  const previewSourceId = watched?.source_id ?? metric?.source_id
  const previewFreq = watched?.freq ?? metric?.freq ?? '5min'

  const save = useMutation({
    mutationFn: (payload: Parameters<typeof createMetric>[0]) =>
      isEditing ? updateMetric(metricId, payload) : createMetric(payload),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: ['catalog'] })
      // ⚠️ 新增后进详情页 —— 那里能看到「哪些任务在用它」；
      //    编辑后回列表 —— 用户多半是来改一个字段的。
      if (isEditing) {
        navigate('/metrics')
      } else {
        const newId = (data as { id?: number })?.id
        navigate(newId ? `/metrics/${newId}` : '/metrics')
      }
    },
  })

  const handleSave = async () => {
    let values: MetricFormValues
    try {
      values = await form.validateFields()
    } catch {
      // 校验没过：错误已经显示在对应表单项上
      return
    }
    save.mutate(buildMetricPayload(values))
  }

  // 指标不存在（编辑模式）
  if (catalog.data && isEditing && !metric) {
    return (
      <div className="page">
        <header className="page__header">
          <h1 className="page__title">指标</h1>
        </header>
        <div className="empty-state">
          <p className="empty-state__title">指标不存在或已被删除</p>
          <Link to="/metrics">← 回到指标列表</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="titlebar">
        <h1>{isEditing ? '编辑指标' : '新增指标'}</h1>
        <div className="titlebar__actions">
          <Link className="link" to="/metrics">
            ← 指标
          </Link>
        </div>
      </header>

      {save.error instanceof Error && (
        <Alert
          type="error"
          showIcon
          message={save.error.message}
          style={{ marginBottom: 16 }}
        />
      )}

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">取数配置</h2>
            <p className="panel__meta mono">
              {source ? `${source.name} · ${source.kind}` : '选择数据源'}
              {metric ? ` · 指标 ${metric.name}` : ''}
            </p>
          </div>
        </div>

        <Form form={form} layout="vertical" requiredMark="optional">
          <MetricFormFields sources={catalog.data?.sources ?? []} />
        </Form>

        <Space size="middle" wrap>
          <Button type="primary" loading={save.isPending} onClick={handleSave}>
            {isEditing ? '保存' : '新增'}
          </Button>
        </Space>
      </section>

      {/* ⚠️ **页内预览** —— 原来这个按钮是跳到另一个页面的（新标签页），
          跳来跳去看不到「改了什么」。
          现在直接在这里画，改 SQL 就能看到图跟着变。 */}
      {previewSourceId ? (
        <section className="panel" aria-labelledby="metricFormPreviewTitle">
          <div className="panel__head">
            <div>
              <h2 className="panel__title" id="metricFormPreviewTitle">
                预览数据
              </h2>
              <p className="panel__meta mono">
                取最近 {windowPoints} 个点 × {previewFreq}
              </p>
            </div>
          </div>
          <MetricChartPanel
            sourceId={previewSourceId}
            config={previewConfig}
            windowPoints={windowPoints}
            freq={previewFreq}
            auto
          />
          {/* ⚠️ **窗口在告警任务里设** —— 指标本身没有这个字段，
              不说清楚用户会在这里找「取多少数据」的开关。 */}
          <p className="muted metric-chart-panel__note">
            这里取的是<strong>最近 {windowPoints} 个点</strong>
            （× {previewFreq}）—— 与告警任务的「窗口点数」一致。
            指标本身没有「取多少数据」的设置，
            要改就去
            {metricJob ? (
              <Link to={`/jobs/${metricJob.id}`}>告警任务</Link>
            ) : (
              '告警任务'
            )}
            里改「窗口点数」
            {metricJob ? '。' : '（这个指标还没有任务，先建一个）。'}
          </p>
        </section>
      ) : null}
    </div>
  )
}
