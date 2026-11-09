/** `/api/platform/archives*` 端点封装。 */
import { request, postJson } from './client'
import type { ArchiveRecord, ArchiveSet, RunSeriesDetail } from './types'

export const listArchiveSets = () =>
  request<{ sets: ArchiveSet[] }>('/api/platform/archives')

export const createArchiveSet = (payload: { name: string; description?: string }) =>
  postJson<ArchiveSet>('/api/platform/archives', payload)

export const deleteArchiveSet = (setId: number) =>
  request<{ deleted: { archive_set_id: number } }>(`/api/platform/archives/${setId}`, {
    method: 'DELETE',
  })

export const getArchiveSet = (setId: number) =>
  request<{ set: ArchiveSet; records: ArchiveRecord[] }>(`/api/platform/archives/${setId}`)

export const archiveDetection = (
  setId: number,
  payload: { run_id: number; series_id: string; description?: string },
) => postJson<ArchiveRecord>(`/api/platform/archives/${setId}/records`, payload)

export const deleteArchiveRecord = (setId: number, recordId: number) =>
  request<{ deleted: { record_id: number } }>(
    `/api/platform/archives/${setId}/records/${recordId}`,
    { method: 'DELETE' },
  )

/** 归档副本的完整时序 —— 结构与平台运行详情一致。 */
export const getArchiveRecordDetail = (recordId: number) =>
  request<RunSeriesDetail>(`/api/platform/archive-records/${recordId}`)
