import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAnnotations, saveAnnotations } from '../../api/annotate'
import { getSeriesValues } from '../../api/series'

export function useSeriesValues(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['seriesValues', seriesId],
    queryFn: () => getSeriesValues(seriesId!),
    enabled: Boolean(seriesId),
  })
}

export function useAnnotations(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['annotations', seriesId],
    queryFn: () => getAnnotations(seriesId!),
    enabled: Boolean(seriesId),
  })
}

export function useSaveAnnotations(seriesId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (intervals: { start: number; end: number; type: string }[]) =>
      saveAnnotations(seriesId!, intervals),
    onSuccess: () => {
      // 保存标注 → 失效 ['annotations', seriesId]（spec §7.2）
      void qc.invalidateQueries({ queryKey: ['annotations', seriesId] })
    },
  })
}
