import { request, postJson } from './client'
import type { AnnotationList } from './types'

/** 标注的读写。序列 ID 含冒号，必须 encodeURIComponent。 */

export const getAnnotations = (seriesId: string) =>
  request<AnnotationList>(`/api/annotate/${encodeURIComponent(seriesId)}`)

export const saveAnnotations = (
  seriesId: string,
  intervals: { start: number; end: number; type: string }[],
) => postJson<{ saved: number; path: string }>(`/api/annotate/${encodeURIComponent(seriesId)}`, {
  intervals,
})
