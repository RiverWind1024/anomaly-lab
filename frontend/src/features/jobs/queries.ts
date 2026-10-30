import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createJob, getCatalog, runJob, toggleJob } from '../../api/platform'
import type { CatalogJob } from '../../api/types'

export const catalogKey = ['catalog'] as const

export function useCatalog() {
  return useQuery({ queryKey: catalogKey, queryFn: getCatalog })
}

/** 「立即运行」是同步的：检测在请求内跑完才返回。所以用 mutation 的 loading 态，不轮询。 */
export function useRunJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: number) => runJob(jobId),
    onSuccess: (_data, jobId) => {
      void qc.invalidateQueries({ queryKey: catalogKey }) // last_run_at / next_run_at 变了
      void qc.invalidateQueries({ queryKey: ['runs', jobId] })
      void qc.invalidateQueries({ queryKey: ['preview', jobId] })
      void qc.invalidateQueries({ queryKey: ['suggestion', jobId] })
    },
  })
}

export function useToggleJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      jobId,
      payload,
    }: {
      jobId: number
      payload: { enabled?: boolean; detector?: string }
    }) => toggleJob(jobId, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: catalogKey }),
  })
}

export function useCreateJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof createJob>[0]) => createJob(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: catalogKey }),
  })
}

/** 任务列表要显示指标名，但任务只带 metric_id。 */
export function jobMetricName(job: CatalogJob, metricNameById: Map<number, string>): string {
  return metricNameById.get(job.metric_id) ?? String(job.metric_id)
}
