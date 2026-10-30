import type { Catalog } from '../../api/types'

export type DeleteTarget = 'source' | 'metric' | 'job'

/**
 * 删除影响的文案。
 *
 * ⚠️ 影响范围**从 catalog 自己算** —— catalog 已经带了全量
 *    sources/metrics/jobs，不值得为了一句提示再开一个端点。
 *
 * ⚠️ 文案必须**具体**（「将连带删除 2 个指标、3 个任务」）——
 *    笼统的「确定吗」会让用户误判影响范围。
 */
export function impactText(target: DeleteTarget, id: number, catalog: Catalog): string {
  if (target === 'job') {
    return '将删除该任务'
  }
  const metrics =
    target === 'source'
      ? catalog.metrics.filter((m) => m.source_id === id)
      : catalog.metrics.filter((m) => m.id === id)
  const metricIds = new Set(metrics.map((m) => m.id))
  const jobs = catalog.jobs.filter((j) => metricIds.has(j.metric_id))

  const parts: string[] = []
  if (target === 'source' && metrics.length > 0) {
    parts.push(`${metrics.length} 个指标`)
  }
  if (jobs.length > 0) {
    parts.push(`${jobs.length} 个任务`)
  }
  if (parts.length === 0) {
    return target === 'source' ? '将删除该数据源' : '将删除该指标'
  }
  return `将连带删除 ${parts.join('、')}`
}
