import { request, postJson } from './client'
import type {
  AlertListResponse,
  AlertRule,
  Catalog,
  Compare,
  FeedbackList,
  Preview,
  RunSummary,
  Suggestion,
} from './types'

/**
 * `/api/platform/*` 的端点封装。
 *
 * 规则：**一个端点一个函数，不碰 React** —— 这样能脱离 React 单测。
 */

export const getCatalog = () => request<Catalog>('/api/platform/catalog')

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

export const createSource = (payload: { name: string; path: string; kind?: string }) =>
  postJson<{ id: number }>('/api/platform/sources', payload)

/**
 * 改数据源。只传要改的字段，其余保持原样。
 *
 * ⚠️ 已经跑过的运行记录不受影响 —— 改动只在**下一次**运行任务时生效。
 */
export const updateSource = (
  sourceId: number,
  payload: { name?: string; path?: string; kind?: string },
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
  freq?: string
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
  window_points?: number
  interval_seconds?: number
  enabled?: boolean
  alert_rules?: AlertRule[] | null
}) => postJson<{ id: number }>('/api/platform/jobs', payload)

/**
 * 改任务配置。
 *
 * ⚠️ 告警规则**不能**自由编辑（spec §8.3）——
 *    只能通过「应用反馈建议」按比例缩放。
 * ⚠️ 改了阈值会**重算规则表**（两者必须一致）；
 *    改其它字段时规则表不动。
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
    window_points?: number
    interval_seconds?: number
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
