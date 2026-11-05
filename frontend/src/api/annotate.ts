import { request, postJson } from './client'
import type { AnnotationList } from './types'

/** 标注的读写。序列 ID 含冒号，必须 encodeURIComponent。 */

/**
 * 读一条序列的标注。
 *
 * ⚠️ **不按 run 分** —— 真值是数据的属性，不是某次运行的属性。
 *    一条标注覆盖所有时间轴包含该时段的检测记录。
 */
export const getAnnotations = (seriesId: string) =>
  request<AnnotationList>(`/api/annotate/${encodeURIComponent(seriesId)}`)

export const saveAnnotations = (
  seriesId: string,
  intervals: {
    /** 「整条记录核对过」不需要边界 —— 窗口从 run_id 取。 */
    start?: string
    end?: string
    type: string
    /** 标这条时它所在层的采样率 —— 反算总体量时用它做权重。 */
    rate?: number
    layer_size?: number
  }[],
  /** 标它时看的是哪次运行 —— 只做溯源，不影响存储路径。 */
  runId?: number,
) =>
  postJson<{ saved: number; path: string }>(
    `/api/annotate/${encodeURIComponent(seriesId)}` + (runId ? `?run_id=${runId}` : ''),
    { intervals },
  )
