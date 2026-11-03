import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  applySuggestion,
  createFeedback,
  createJob,
  getCatalog,
  getCompare,
  getFeedback,
  getPreview,
  getRuns,
  getSuggestion,
  runJob,
  testRunJob,
  toggleJob,
  updateJob,
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
export function usePreview(
  jobId: number,
  runId?: number,
  seriesId?: string,
  enabled = true,
) {
  return useQuery({
    queryKey: ['preview', jobId, runId, seriesId],
    queryFn: () => getPreview(jobId, { runId, seriesId }),
    enabled: enabled && jobId > 0,
  })
}

export function useRuns(jobId: number, enabled = true) {
  return useQuery({
    queryKey: ['runs', jobId],
    queryFn: () => getRuns(jobId),
    enabled: enabled && jobId > 0,
    // 只在有 run 处于 running 时继续轮询；空闲时停（spec §7.3）
    refetchInterval: (query) => {
      const runs = query.state.data?.runs ?? []
      return runs.some((r) => r.status === 'running') ? 3000 : false
    },
  })
}

export function useCompare(
  jobId: number,
  seriesId?: string,
  detectors?: string[],
  enabled = true,
) {
  return useQuery({
    queryKey: ['compare', jobId, seriesId, detectors],
    queryFn: () => getCompare(jobId, { seriesId, detectors }),
    enabled: enabled && jobId > 0,
  })
}

/** 人工反馈历史。 */
export function useFeedback(jobId: number, enabled = true) {
  return useQuery({
    queryKey: ['feedback', jobId],
    queryFn: () => getFeedback(jobId),
    enabled: enabled && jobId > 0,
  })
}

/**
 * 调参建议。
 *
 * 后端会**重新取数并跑一遍候选算法** —— 比预览慢，返回的是
 * 「用哪个算法 + 用哪个倍数」的建议。
 */
export function useSuggestion(jobId: number, runId?: number, enabled = true) {
  return useQuery({
    queryKey: ['suggestion', jobId, runId],
    queryFn: () => getSuggestion(jobId, runId),
    enabled: enabled && jobId > 0,
  })
}

export function useCreateFeedback() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof createFeedback>[0]) => createFeedback(payload),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['feedback', vars.job_id] })
      void qc.invalidateQueries({ queryKey: ['suggestion', vars.job_id] })
    },
  })
}

export function useApplySuggestion(jobId: number) {
  const qc = useQueryClient()
  return useMutation({
    // ⚠️ 不能写 `Parameters<typeof applySuggestion>[0]` —— applySuggestion 有两个参数
    // （jobId, payload），`[0]` 取到的是 jobId，类型直接对不上。
    mutationFn: (payload: { multiplier: number; detector?: string }) =>
      applySuggestion(jobId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: catalogKey }) // 任务配置变了
      void qc.invalidateQueries({ queryKey: ['suggestion', jobId] })
      // ⚠️ compare 的失效不能省 —— compare 响应里带**当前**的 alert_rules 与
      // band_width，不刷新就会拿旧倍数解读对比结果（spec §7.2）。
      void qc.invalidateQueries({ queryKey: ['compare', jobId] })
      void qc.invalidateQueries({ queryKey: ['preview', jobId] })
    },
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

/**
 * 试跑：真实执行一次检测，但**不落库**。
 *
 * ⚠️ 不失效任何缓存 —— 试跑没有产生 run 记录，
 *    运行记录、预览、告警中心都还是上次真跑的样子。
 */
export function useTestRunJob() {
  return useMutation({
    mutationFn: (jobId: number) => testRunJob(jobId),
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

/**
 * 改任务配置。
 *
 * 成功后要失效的不只是 catalog —— 预览与对比的响应里带着**当前的**
 * 告警规则与倍数，不刷新就会拿旧规则解读新结果（spec §7.2）。
 */
export function useUpdateJob(jobId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof updateJob>[1]) => updateJob(jobId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: catalogKey })
      void qc.invalidateQueries({ queryKey: ['preview', jobId] })
      void qc.invalidateQueries({ queryKey: ['compare', jobId] })
    },
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
