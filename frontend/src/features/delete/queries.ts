import { useMutation, useQueryClient } from '@tanstack/react-query'
import { deleteJob, deleteMetric, deleteSource } from '../../api/platform'
import { catalogKey } from '../jobs/queries'

/**
 * 删除的 mutation。
 *
 * 成功后只需失效 `catalog` —— 三个列表页的数据全在 catalog 里。
 */
function useDeleteMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: catalogKey })
    },
  })
}

export const useDeleteJob = () => useDeleteMutation((jobId: number) => deleteJob(jobId))

export const useDeleteMetric = () =>
  useDeleteMutation((metricId: number) => deleteMetric(metricId))

export const useDeleteSource = () =>
  useDeleteMutation((sourceId: number) => deleteSource(sourceId))
