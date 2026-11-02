import { useQuery } from '@tanstack/react-query'
import { getBadcases } from '../../api/series'

/**
 * 单条序列的检测详情（数值 + 分数 + 误报漏报区间）。
 *
 * 序列总览的详情抽屉与检测记录页共用这一个查询 ——
 * 同一份数据不该有两个 query key。
 *
 * ⚠️ `detector` 参与 query key —— 一条序列在不同算法下的检测结果**是两份数据**，
 *    混在一个 key 里会串（先看 iqr 再看 mad，图会变成 mad 的但标题还写着 iqr）。
 */
export function useDetectionDetail(seriesId: string | undefined, detector?: string) {
  return useQuery({
    queryKey: ['detection-detail', seriesId, detector],
    queryFn: () => getBadcases(seriesId!, detector),
    enabled: Boolean(seriesId),
  })
}
