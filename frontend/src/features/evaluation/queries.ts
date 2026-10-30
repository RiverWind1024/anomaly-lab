import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { excludeEvaluationRow, getSummary, restoreEvaluationRow } from '../../api/series'

export function useSummary() {
  return useQuery({ queryKey: ['summary'], queryFn: getSummary })
}

/**
 * 排除一条检测记录。
 *
 * ⚠️ 不是删 report.json —— 那是 `make evaluate` 的产物，重跑会覆盖回来。
 *    排除项存盘，可恢复。
 */
export function useExcludeEvaluationRow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { series_id: string; detector: string }) =>
      excludeEvaluationRow(payload.series_id, payload.detector),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['summary'] }),
  })
}

/** 恢复一条被排除的检测记录。 */
export function useRestoreEvaluationRow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { series_id: string; detector: string }) =>
      restoreEvaluationRow(payload.series_id, payload.detector),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['summary'] }),
  })
}
