import { useQuery } from '@tanstack/react-query'
import { getOverview } from '../../api/platform'

export const overviewKey = ['overview'] as const

/**
 * 平台运行概况。
 *
 * ⚠️ 一次请求拿全 —— 让前端自己拼的话，每个任务都要单独查 runs 与 feedback。
 */
export function useOverview() {
  return useQuery({ queryKey: overviewKey, queryFn: getOverview })
}
