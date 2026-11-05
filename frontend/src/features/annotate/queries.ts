import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAnnotations, saveAnnotations } from '../../api/annotate'
import { getProductionSamples, getRunSeriesDetail, getSeriesValues } from '../../api/series'

export function useSeriesValues(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['seriesValues', seriesId],
    queryFn: () => getSeriesValues(seriesId!),
    enabled: Boolean(seriesId),
  })
}

/**
 * 一条序列的标注。
 *
 * ⚠️ **不按 run 分** —— 真值是数据的属性，一条标注覆盖所有
 *    时间轴包含该时段的检测记录。
 */
export function useAnnotations(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['annotations', seriesId],
    queryFn: () => getAnnotations(seriesId!),
    enabled: Boolean(seriesId),
  })
}

export function useSaveAnnotations(seriesId: string | undefined, runId?: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (
      intervals: {
        start?: string
        end?: string
        type: string
        rate?: number
        layer_size?: number
      }[],
    ) =>
      saveAnnotations(seriesId!, intervals, runId),
    onSuccess: () => {
      // 保存标注 → 失效 ['annotations', seriesId]（spec §7.2）
      void qc.invalidateQueries({ queryKey: ['annotations', seriesId] })
      // ⚠️ 采样清单与评估结果也依赖标注（「已核对」状态、覆盖率）——
      //    不失效的话点完「这条记录正常」界面还是「待核对」。
      void qc.invalidateQueries({ queryKey: ['productionSamples'] })
      void qc.invalidateQueries({ queryKey: ['productionEvaluation'] })
    },
  })
}

/** 可标注的生产检测记录清单。 */
export function useProductionSamples(limit = 50) {
  return useQuery({
    queryKey: ['productionSamples', limit],
    queryFn: () => getProductionSamples(limit),
  })
}

/** 某次运行里一条序列的完整时序（波形 + 分数 + 告警等级）。 */
export function useRunSeriesDetail(
  runId: number | undefined,
  seriesId: string | undefined,
) {
  return useQuery({
    queryKey: ['runSeriesDetail', runId, seriesId],
    queryFn: () => getRunSeriesDetail(runId!, seriesId!),
    enabled: Boolean(runId && seriesId),
  })
}
