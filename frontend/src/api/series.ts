import { request } from './client'
import type { Badcases, SeriesMeta, SeriesValues, Summary } from './types'

/** `/api/series*` 与 `/api/summary`、`/api/badcases` 的端点封装。 */

export const getSeries = () => request<SeriesMeta[]>('/api/series')

export const getSeriesValues = (seriesId: string) =>
  request<SeriesValues>(`/api/series/${encodeURIComponent(seriesId)}/values`)

export const getSummary = () => request<Summary>('/api/summary')

export const getBadcases = (seriesId: string) =>
  request<Badcases>(`/api/badcases?series_id=${encodeURIComponent(seriesId)}`)
