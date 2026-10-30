import { useQuery } from '@tanstack/react-query'
import { getBadcases } from '../../api/series'

/**
 * 单条序列的检测详情（数值 + 分数 + 误报漏报区间）。
 *
 * 序列总览的详情抽屉与检测记录页共用这一个查询 ——
 * 同一份数据不该有两个 query key。
 */
export function useDetectionDetail(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['detection-detail', seriesId],
    queryFn: () => getBadcases(seriesId!),
    enabled: Boolean(seriesId),
  })
}
