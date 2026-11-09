import { request, postJson } from './client'
import type {
  AlertListResponse,
  AlertRule,
  Catalog,
  Compare,
  DetectionRecordList,
  FeedbackList,
  LabExperiment,
  LabExperimentSummary,
  LabInspectResult,
  LabJobDraft,
  LabRunResult,
  LabEvaluateResult,
  LabWindowDetail,
  Observability,
  Overview,
  Preview,
  PruneResult,
  RunSummary,
  SourceConfig,
  SourceQueryResult,
  StorageUsage,
  Suggestion,
  TestRunResult,
} from './types'

/**
 * `/api/platform/*` 的端点封装。
 *
 * 规则：**一个端点一个函数，不碰 React** —— 这样能脱离 React 单测。
 */

export const getCatalog = () => request<Catalog>('/api/platform/catalog')

/**
 * 平台运行概况（概览页）。
 *
 * ⚠️ 一次请求拿全 —— 让前端自己拼的话，每个任务都要单独查 runs 与 feedback。
 */
export const getOverview = () => request<Overview>('/api/platform/overview')

/**
 * 跨任务汇总告警事件。
 *
 * ⚠️ 以每个任务的**最新一次运行**为准 —— 滚动窗口下同一段异常会被
 *    连续多次运行重复报出。
 */
export const getAlerts = (opts: {
  jobId?: number
  level?: string
  seriesId?: string
  since?: string
  until?: string
} = {}) => {
  const params = new URLSearchParams()
  if (opts.jobId !== undefined) params.set('job_id', String(opts.jobId))
  if (opts.level) params.set('level', opts.level)
  if (opts.seriesId) params.set('series_id', opts.seriesId)
  if (opts.since) params.set('since', opts.since)
  if (opts.until) params.set('until', opts.until)
  const qs = params.toString()
  return request<AlertListResponse>(`/api/platform/alerts${qs ? `?${qs}` : ''}`)
}

export const createSource = (payload: {
  name: string
  path?: string
  kind?: string
  config?: SourceConfig
}) => postJson<{ id: number }>('/api/platform/sources', payload)

/**
 * **平台运行产生的检测记录** —— 每次运行 × 每条序列。
 *
 * ⚠️ 与 `/api/summary`（离线回测报告）刻意分开：混在一张表里
 *    分不清「算法在合成集上的上限」和「任务实际跑出了什么」。
 */
export const getDetectionRecords = (opts: {
  jobId?: number
  onlyAlerts?: boolean
  limit?: number
  offset?: number
} = {}) => {
  const params = new URLSearchParams()
  if (opts.jobId !== undefined) params.set('job_id', String(opts.jobId))
  if (opts.onlyAlerts) params.set('only_alerts', 'true')
  if (opts.limit !== undefined) params.set('limit', String(opts.limit))
  if (opts.offset !== undefined) params.set('offset', String(opts.offset))
  const qs = params.toString()
  return request<DetectionRecordList>(`/api/platform/detections${qs ? `?${qs}` : ''}`)
}

/**
 * 数据浏览：在数据源上执行一段只读 SQL，返回列结构与前 N 行。
 *
 * ⚠️ 这是**浏览** —— 不落库、不建指标，只是让用户「先看结构、再定指标」。
 * ⚠️ `time_column` 只有 SQL 里带 `$timefilter` 时才需要。
 */
export const querySource = (
  sourceId: number,
  payload: {
    sql: string
    start?: string
    end?: string
    limit?: number
    time_column?: string
    time_format?: string
    source_timezone?: string
  },
) => postJson<SourceQueryResult>(`/api/platform/sources/${sourceId}/query`, payload)

/**
 * 改数据源。只传要改的字段，其余保持原样。
 *
 * ⚠️ 已经跑过的运行记录不受影响 —— 改动只在**下一次**运行任务时生效。
 * ⚠️ `config` 一旦传了就是**整体替换** —— 没传的顶层键会被删掉。
 */
export const updateSource = (
  sourceId: number,
  payload: { name?: string; path?: string; kind?: string; config?: SourceConfig },
) =>
  request<unknown>(`/api/platform/sources/${sourceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const createMetric = (payload: {
  source_id: number
  name: string
  query: string
  time_column: string
  value_column: string
  group_column?: string | null
  time_format?: string
  source_timezone?: string
  missing_policy?: string
}) => postJson<{ id: number }>('/api/platform/metrics', payload)

/**
 * 改指标。只传要改的字段，其余保持原样。
 *
 * ⚠️ `group_column: null` 是**显式清空** —— 想清空就必须传 null，
 *    不传则保持原值。
 */
export const updateMetric = (
  metricId: number,
  payload: Partial<Parameters<typeof createMetric>[0]>,
) =>
  request<unknown>(`/api/platform/metrics/${metricId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const createJob = (payload: {
  metric_id: number
  name: string
  detector?: string
  alert_threshold?: number
  critical_threshold?: number
  window_seconds?: number
  interval_seconds?: number
  detect_points?: number
  enabled?: boolean
  alert_rules?: AlertRule[] | null
  alert_direction?: 'both' | 'above' | 'below'
}) => postJson<{ id: number }>('/api/platform/jobs', payload)

/**
 * 改任务配置。
 *
 * ⚠️ 告警规则**可以**自由编辑了（之前只读）——
 *    阈值恰恰是最常调的东西，锁在「新建任务时」是锁错了地方。
 * ⚠️ 改了阈值会**重算规则表**（两者必须一致）；
 *    改其它字段时规则表不动；
 *    显式传了 `alert_rules` 则**反过来** —— 阈值跟着规则表走。
 */
export const updateJob = (
  jobId: number,
  payload: {
    name?: string
    metric_id?: number
    enabled?: boolean
    detector?: string
    alert_threshold?: number
    critical_threshold?: number
    window_seconds?: number
    interval_seconds?: number
    detect_points?: number
    alert_rules?: AlertRule[]
    alert_direction?: 'both' | 'above' | 'below'
  },
) =>
  request<unknown>(`/api/platform/jobs/${jobId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

/** 只改启用状态 / 算法 —— updateJob 的特例。 */
export const toggleJob = (jobId: number, payload: { enabled?: boolean; detector?: string }) =>
  updateJob(jobId, payload)

export const runJob = (jobId: number) =>
  postJson<{ run_id: number }>(`/api/platform/jobs/${jobId}/run`, {})

/**
 * 试跑一次检测：真实执行，但**不落库**。
 *
 * ⚠️ 与 `runJob` 的区别只有「不写 runs 表、不写结果文件」——
 *    取数、检测器选择、打分、分级全都走同一段代码。
 * ⚠️ 所以「试跑看到的告警」就是「真跑一次会得到的告警」。
 */
export const testRunJob = (jobId: number) =>
  postJson<TestRunResult>(`/api/platform/jobs/${jobId}/test-run`, {})

export const getRuns = (jobId: number) =>
  request<{ runs: RunSummary[] }>(`/api/platform/jobs/${jobId}/runs`)

export const getPreview = (jobId: number, opts: { runId?: number; seriesId?: string } = {}) => {
  const params = new URLSearchParams()
  if (opts.runId !== undefined) params.set('run_id', String(opts.runId))
  if (opts.seriesId) params.set('series_id', opts.seriesId)
  const qs = params.toString()
  return request<Preview>(`/api/platform/jobs/${jobId}/preview${qs ? `?${qs}` : ''}`)
}

export const getCompare = (jobId: number, opts: { seriesId?: string; detectors?: string[] } = {}) => {
  const params = new URLSearchParams()
  if (opts.seriesId) params.set('series_id', opts.seriesId)
  if (opts.detectors?.length) params.set('detectors', opts.detectors.join(','))
  const qs = params.toString()
  return request<Compare>(`/api/platform/jobs/${jobId}/compare${qs ? `?${qs}` : ''}`)
}

/**
 * 提交反馈。
 * ⚠️ POST 端点是 `/api/platform/feedback`（**与任务无关**），
 * 不是 `/api/platform/jobs/{id}/feedback` —— 后者只注册了 GET。
 * ⚠️ 字段是 start_ts / end_ts（不是 start / end），且必须带 job_id。
 */
export const createFeedback = (payload: {
  job_id: number
  series_id: string
  start_ts: string
  end_ts: string
  kind: string
  note?: string
  run_id?: number | null
}) => postJson<{ id: number }>('/api/platform/feedback', payload)

export const getFeedback = (jobId: number) =>
  request<FeedbackList>(`/api/platform/jobs/${jobId}/feedback`)

export const getSuggestion = (jobId: number, runId?: number) => {
  const qs = runId === undefined ? '' : `?run_id=${runId}`
  return request<Suggestion>(`/api/platform/jobs/${jobId}/feedback/suggestion${qs}`)
}

export const applySuggestion = (jobId: number, payload: { multiplier: number; detector?: string }) =>
  postJson<unknown>(`/api/platform/jobs/${jobId}/apply-suggestion`, payload)

/**
 * 删除的统计（级联删掉了多少东西）。
 *
 * ⚠️ 后端会把内部的 `run_ids` pop 掉再返回 —— 响应里只有计数。
 */
export interface DeleteStats {
  sources?: number
  metrics: number
  jobs: number
  runs: number
  feedback: number
}

export const deleteJob = (jobId: number) =>
  request<{ deleted: DeleteStats }>(`/api/platform/jobs/${jobId}`, { method: 'DELETE' })

export const deleteMetric = (metricId: number) =>
  request<{ deleted: DeleteStats }>(`/api/platform/metrics/${metricId}`, { method: 'DELETE' })

export const deleteSource = (sourceId: number) =>
  request<{ deleted: DeleteStats }>(`/api/platform/sources/${sourceId}`, { method: 'DELETE' })

/** 删除一条检测记录（不可恢复；归档副本不受影响）。 */
export const deleteDetection = (runId: number, seriesId: string) =>
  request<{ deleted: number; run_id: number; series_id: string }>(
    `/api/platform/detections/${runId}/${encodeURIComponent(seriesId)}`,
    { method: 'DELETE' },
  )

/**
 * 存储占用与保留策略。
 *
 * ⚠️ 「自动清理」不可见的话，用户没法判断它在不在工作 ——
 *    作品集演示时，「数据在自动滚动」本身就是个卖点。
 */
export const getStorage = () => request<StorageUsage>('/api/platform/storage')

/**
 * 服务自身状态：当前值 + 最近 N 分钟的时序 + 算法/接口/任务统计。
 *
 * ⚠️ 一次拿全 —— 监控页每 15 秒刷新，拆成五个端点就是五倍的请求。
 */
export const getObservability = (windowMinutes = 60) =>
  request<Observability>(`/api/platform/observability?window_minutes=${windowMinutes}`)

/**
 * 立即清理超出保留窗口的数据。
 *
 * ⚠️ 调度器本来就会每小时自动清一次 —— 这个是「现在就清」的手动入口。
 */
export const pruneData = () => postJson<PruneResult>('/api/platform/prune', {})

/**
 * 指标预检（Lab）—— 取一段真实数据，做采样 / 体检 / 形态推断。
 *
 * ⚠️ P0 不跑检测、不落盘、不建任务 —— 只是让用户在建任务前看清数据。
 * ⚠️ `freq` 在 `kind="metric"` 时必须省略（继承指标）；
 *    临时 SQL 必须显式给 `freq`，否则后端无法切窗。
 */
export const inspectLab = (payload: {
  kind: 'metric' | 'sql' | 'synthetic' | 'public'
  start: string
  end: string
  metric_id?: number
  source_id?: number
  sql?: string
  time_column?: string
  value_column?: string
  group_column?: string | null
  time_format?: string
  source_timezone?: string
  freq?: string
  missing_policy?: string
  max_series?: number
  sampling?: Partial<{
    mode: 'recent' | 'even' | 'stratified'
    window_points: number
    stride_points: number | null
    max_points: number
    max_windows: number
    min_valid_ratio: number
    seed: number
  }>
  /** 真值来源：`none` = 无真值；`annotation` = 读人工标注。 */
  truth?: 'none' | 'annotation'
  synthetic?: {
    metric_class: string
    n_points: number
    n_anomalies: number
    anomaly_types?: string[]
    seed: number
  }
  public?: {
    dataset: 'nab' | 'ucr'
    name?: string | null
    limit: number
  }
}) => postJson<LabInspectResult>('/api/lab/inspect', payload)

/**
 * 指标预检实验（Lab）—— 在同一批窗口上跑多个检测器，产出对比画像。
 *
 * ⚠️ **不落盘** —— 产物全在响应里。
 * ⚠️ `detectors` 留空 → 后端用 `auto` + 形态推荐的候选。
 */
export const runLab = (payload: {
  kind: 'metric' | 'sql' | 'synthetic' | 'public'
  start: string
  end: string
  metric_id?: number
  source_id?: number
  sql?: string
  time_column?: string
  value_column?: string
  group_column?: string | null
  time_format?: string
  source_timezone?: string
  freq?: string
  missing_policy?: string
  max_series?: number
  sampling?: Partial<{
    mode: 'recent' | 'even' | 'stratified'
    window_points: number
    stride_points: number | null
    max_points: number
    max_windows: number
    min_valid_ratio: number
    seed: number
  }>
  /** 真值来源：`none` = 无真值；`annotation` = 读人工标注。 */
  truth?: 'none' | 'annotation'
  synthetic?: {
    metric_class: string
    n_points: number
    n_anomalies: number
    anomaly_types?: string[]
    seed: number
  }
  public?: {
    dataset: 'nab' | 'ucr'
    name?: string | null
    limit: number
  }
  detectors?: string[]
  multipliers?: number[]
}) => postJson<LabRunResult>('/api/lab/run', payload)

/**
 * 有真值的评估 —— 校准集选阈值，测试集报 F1。
 *
 * ⚠️ **与 `/api/lab/run` 的区别**：`run` 不需要真值，产出的是检出画像；
 *    `evaluate` 需要点级真值，产出的是 P / R / F1。
 */
export const evaluateLab = (payload: {
  kind: 'metric' | 'sql' | 'synthetic' | 'public'
  start: string
  end: string
  metric_id?: number
  source_id?: number
  sql?: string
  time_column?: string
  value_column?: string
  group_column?: string | null
  time_format?: string
  source_timezone?: string
  freq?: string
  missing_policy?: string
  max_series?: number
  sampling?: Partial<{
    mode: 'recent' | 'even' | 'stratified'
    window_points: number
    stride_points: number | null
    max_points: number
    max_windows: number
    min_valid_ratio: number
    seed: number
  }>
  /** 真值来源：`none` = 无真值；`annotation` = 读人工标注。 */
  truth?: 'none' | 'annotation'
  synthetic?: {
    metric_class: string
    n_points: number
    n_anomalies: number
    anomaly_types?: string[]
    seed: number
  }
  public?: {
    dataset: 'nab' | 'ucr'
    name?: string | null
    limit: number
  }
  detectors?: string[]
  multipliers?: number[]
  /** 校准 / 测试的切分比例 —— 前一份校准，后一份测试。 */
  split_ratio?: number
}) => postJson<LabEvaluateResult>('/api/lab/evaluate', payload)

/**
 * 保存一条实验记录 —— spec + env + result 落盘，可复现。
 *
 * ⚠️ `result` 就是 `/api/lab/run` 的返回 —— 后端**不重跑**，
 *    记录的就是屏幕上看到的那一份。
 */
export const saveLabExperiment = (payload: {
  kind: 'metric' | 'sql' | 'synthetic' | 'public'
  start: string
  end: string
  metric_id?: number
  source_id?: number
  sql?: string
  time_column?: string
  value_column?: string
  group_column?: string | null
  time_format?: string
  source_timezone?: string
  freq?: string
  missing_policy?: string
  max_series?: number
  sampling?: Partial<{
    mode: 'recent' | 'even' | 'stratified'
    window_points: number
    stride_points: number | null
    max_points: number
    max_windows: number
    min_valid_ratio: number
    seed: number
  }>
  /** 真值来源：`none` = 无真值；`annotation` = 读人工标注。 */
  truth?: 'none' | 'annotation'
  synthetic?: {
    metric_class: string
    n_points: number
    n_anomalies: number
    anomaly_types?: string[]
    seed: number
  }
  public?: {
    dataset: 'nab' | 'ucr'
    name?: string | null
    limit: number
  }
  detectors?: string[]
  multipliers?: number[]
  result: LabRunResult
}) => postJson<LabExperimentSummary>('/api/lab/experiments', payload)

/** 实验记录列表 —— 新的在前。 */
export const listLabExperiments = () => request<LabExperimentSummary[]>('/api/lab/experiments')

/** 实验记录详情（含完整结果）。 */
export const getLabExperiment = (id: string) => request<LabExperiment>(`/api/lab/experiments/${id}`)

/**
 * 从实验记录生成任务草稿 —— **只回填表单，不创建任务**。
 *
 * ⚠️ 用 POST 而不是 GET：草稿要按记录里的结果算出来，不是静态资源。
 */
export const getLabJobDraft = (id: string) =>
  postJson<LabJobDraft>(`/api/lab/experiments/${id}/job-draft`, {})

/**
 * 拉单个窗口的时序数据（画图用）。
 *
 * ⚠️ **按需拉取** —— 一次实验可能上百个窗口，全量带曲线会把响应撑爆。
 */
export const getLabWindow = (payload: {
  kind: 'metric' | 'sql'
  start: string
  end: string
  metric_id?: number
  source_id?: number
  sql?: string
  time_column?: string
  value_column?: string
  group_column?: string | null
  time_format?: string
  source_timezone?: string
  freq?: string
  missing_policy?: string
  max_series?: number
  sampling?: Partial<{
    mode: 'recent' | 'even' | 'stratified'
    window_points: number
    stride_points: number | null
    max_points: number
    max_windows: number
    min_valid_ratio: number
    seed: number
  }>
  series_id: string
  window_index: number
  detectors?: string[]
}) => postJson<LabWindowDetail>('/api/lab/window', payload)
