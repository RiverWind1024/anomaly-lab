import { request, postJson } from './client'
import type { Badcases, SeriesMeta, SeriesValues, Summary } from './types'

/** `/api/series*` 与 `/api/summary`、`/api/badcases` 的端点封装。 */

export const getSeries = () => request<SeriesMeta[]>('/api/series')

export const getSeriesValues = (seriesId: string) =>
  request<SeriesValues>(`/api/series/${encodeURIComponent(seriesId)}/values`)

export const getSummary = () => request<Summary>('/api/summary')

export const getBadcases = (seriesId: string) =>
  request<Badcases>(`/api/badcases?series_id=${encodeURIComponent(seriesId)}`)

/** 被排除的检测记录。 */
export interface Exclusion {
  key: string
  series_id: string
  detector: string
  excluded_at: string
}

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
