import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createJob,
  getCatalog,
  getCompare,
  getPreview,
  getRuns,
  runJob,
  toggleJob,
} from '../../api/platform'
import type { CatalogJob } from '../../api/types'

export const catalogKey = ['catalog'] as const

export function useCatalog() {
  return useQuery({ queryKey: catalogKey, queryFn: getCatalog })
}

/**
 * 预览数据。
 *
 * ⚠️ 数据不足是 **200 + sufficient:false**，不是 404 —— 所以不要用 error 判断，
 *    要读响应体里的 `sufficient` / `insufficient_reason`。
 */
export function usePreview(jobId: number, runId?: number, seriesId?: string) {
  return useQuery({
    queryKey: ['preview', jobId, runId, seriesId],
    queryFn: () => getPreview(jobId, { runId, seriesId }),
    enabled: jobId > 0,
  })
}

export function useRuns(jobId: number) {
  return useQuery({
    queryKey: ['runs', jobId],
    queryFn: () => getRuns(jobId),
    enabled: jobId > 0,
    // 只在有 run 处于 running 时继续轮询；空闲时停（spec §7.3）
    refetchInterval: (query) => {
      const runs = query.state.data?.runs ?? []
      return runs.some((r) => r.status === 'running') ? 3000 : false
    },
  })
}

export function useCompare(jobId: number, seriesId?: string, detectors?: string[]) {
  return useQuery({
    queryKey: ['compare', jobId, seriesId, detectors],
    queryFn: () => getCompare(jobId, { seriesId, detectors }),
    enabled: jobId > 0,
  })
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
