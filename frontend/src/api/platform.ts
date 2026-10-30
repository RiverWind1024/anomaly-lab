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

/** PATCH 只支持 enabled 与 detector —— 告警规则**不能**自由编辑（spec §8.3）。 */
export const toggleJob = (jobId: number, payload: { enabled?: boolean; detector?: string }) =>
  request<unknown>(`/api/platform/jobs/${jobId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

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
