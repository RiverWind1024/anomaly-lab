import { useQuery } from '@tanstack/react-query'
import { getSeries } from '../../api/series'

export const seriesKey = ['series'] as const

/**
 * 序列总览的数据源。
 *
 * 注意：`/api/series` 返回的是**数组**（不是 { series: [...] }）——
 * 后端 `list_series()` 直接返回 list[dict]。client.ts 原样透传，类型是 SeriesMeta[]。
 */
export function useSeries() {
  return useQuery({ queryKey: seriesKey, queryFn: getSeries })
}
