import { useQuery } from '@tanstack/react-query'
import { getObservability } from '../../api/platform'

/**
 * 服务监控数据。
 *
 * ⚠️ 15 秒刷新一次 —— 采样线程本身是 60 秒一个点，页面刷太快没有新数据，
 *    只是白白多打几次接口；刷太慢又看不出「刚才那次请求卡了」。
 */
export function useObservability(windowMinutes = 60) {
  return useQuery({
    queryKey: ['observability', windowMinutes],
    queryFn: () => getObservability(windowMinutes),
    refetchInterval: 15_000,
  })
}
