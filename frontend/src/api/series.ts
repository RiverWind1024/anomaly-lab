import { request, postJson } from './client'
import type {
  Badcases,
  Exclusion,
  ProductionEvaluation,
  ProductionSample,
  RunSeriesDetail,
  SeriesMeta,
  SeriesValues,
  Summary,
} from './types'

/** `/api/series*` 与 `/api/summary`、`/api/badcases` 的端点封装。 */

export const getSeries = () => request<SeriesMeta[]>('/api/series')

export const getSeriesValues = (seriesId: string) =>
  request<SeriesValues>(`/api/series/${encodeURIComponent(seriesId)}/values`)

export const getSummary = () => request<Summary>('/api/summary')

export const getBadcases = (seriesId: string, detector?: string) =>
  request<Badcases>(
    `/api/badcases?series_id=${encodeURIComponent(seriesId)}` +
      (detector ? `&detector=${encodeURIComponent(detector)}` : ''),
  )

/**
 * 生产检测记录的评估结果（人工标注 × 线上跑的那次）。
 *
 * ⚠️ **只覆盖被标注过的那部分** —— 真值是人工标的，不是全集。
 */
/**
 * 生产检测记录的评估结果。
 *
 * ⚠️ `rateAlert` / `rateNormal` 是**两层的采样率** ——
 * 正常记录（什么都没报）远多于异常记录，同一个采样率要么标不完、
 * 要么异常样本太少。
 */
export const getProductionEvaluation = (
  jobId?: number,
  rateAlert?: number,
  rateNormal?: number,
  maxPerLayer?: number,
) => {
  const params = new URLSearchParams()
  if (jobId) params.set('job_id', String(jobId))
  if (rateAlert !== undefined) params.set('rate_alert', String(rateAlert))
  if (rateNormal !== undefined) params.set('rate_normal', String(rateNormal))
  if (maxPerLayer !== undefined) params.set('max_per_layer', String(maxPerLayer))
  const query = params.toString()
  return request<ProductionEvaluation>(
    `/api/evaluation/production${query ? `?${query}` : ''}`,
  )
}

/**
 * 采样后的生产检测记录清单 —— 标注页的下拉用它。
 *
 * ⚠️ `todo=true` → 只给还没标的（待办队列）。
 */
export const getProductionSamples = (
  limit = 50,
  rateAlert?: number,
  rateNormal?: number,
  todo = false,
) => {
  const params = new URLSearchParams({ limit: String(limit) })
  if (rateAlert !== undefined) params.set('rate_alert', String(rateAlert))
  if (rateNormal !== undefined) params.set('rate_normal', String(rateNormal))
  if (todo) params.set('todo', 'true')
  return request<ProductionSample[]>(
    `/api/evaluation/production/samples?${params.toString()}`,
  )
}

/**
 * 某次运行里一条序列的完整时序。
 *
 * ⚠️ 直接读 run 的产物 —— 跟当时跑的那份完全一致，不重新取数。
 */
export const getRunSeriesDetail = (runId: number, seriesId: string) =>
  request<RunSeriesDetail>(
    `/api/runs/${runId}/series/${encodeURIComponent(seriesId)}`,
  )

export const getExclusions = () =>
  request<{ excluded: Exclusion[] }>('/api/evaluation/exclusions')

/**
 * 排除一条检测记录（序列 + 算法）。
 *
 * ⚠️ 不是删 report.json —— 那是 `make evaluate` 的产物，重跑会覆盖回来。
 *    排除项单独存盘，可恢复。
 */
export const excludeEvaluationRow = (seriesId: string, detector: string) =>
  postJson<Exclusion>('/api/evaluation/exclusions', {
    series_id: seriesId,
    detector,
  })

/** 恢复一条被排除的检测记录。 */
export const restoreEvaluationRow = (seriesId: string, detector: string) =>
  request<unknown>(
    `/api/evaluation/exclusions/${encodeURIComponent(seriesId)}/${encodeURIComponent(detector)}`,
    { method: 'DELETE' },
  )
