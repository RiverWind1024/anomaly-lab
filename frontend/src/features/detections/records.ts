/**
 * 检测记录页的纯逻辑：记录的身份、选中项解析、分页切片。
 *
 * ⚠️ **独立成文件** —— 这些是能脱离 React 测的纯函数，
 *    混在组件里就只能靠渲染整个页面来测。
 */

import type { EvaluationRow } from '../../api/types'

/**
 * 一条检测记录的身份 —— **序列 × 算法**。
 *
 * ⚠️ 不是只有序列 —— 同一序列在不同算法下是**两条不同的记录**。
 *    只按序列比较会把它们混成一条（而且两个都高亮）。
 */
export interface RecordKey {
  series_id: string
  /** 检测算法；URL 没给时按报告里的第一条记录解析。 */
  detector?: string
}

/** 记录的稳定 key（React key + 比较用）。 */
export function recordKey(row: { series_id: string; detector: string }): string {
  return `${row.series_id}@@${row.detector}`
}

/**
 * 从 URL 参数解析出选中的记录。
 *
 * ⚠️ **只有 `series_id` 时按报告解析算法** —— 旧深链接（评估页改造前发出的）
 *    只有序列号，得靠报告补出算法名，否则详情会退回到后端默认的 iqr。
 *
 * ⚠️ 报告里**根本没有**这条序列时，`detector` 留空 ——
 *    让详情端点按默认算法去试，比什么都不显示更有用
 *    （端点会回「该序列还没有检测结果」，那才是真相）。
 */
export function resolveSelected(
  rows: EvaluationRow[],
  seriesId: string | undefined,
  detector: string | undefined,
): RecordKey | undefined {
  if (!seriesId) return undefined
  if (detector) return { series_id: seriesId, detector }
  const hit = rows.find((row) => row.series_id === seriesId)
  return { series_id: seriesId, detector: hit?.detector }
}

/**
 * 这行是不是当前选中的那条。
 *
 * ⚠️ **必须两个字段都比** —— 只比序列会让同序列的所有算法一起高亮。
 */
export function isSelectedRow(
  row: EvaluationRow,
  selected: RecordKey | undefined,
): boolean {
  if (!selected) return false
  if (row.series_id !== selected.series_id) return false
  if (selected.detector === undefined) return true
  return row.detector === selected.detector
}

/** 分页切片。 */
export function paginate<T>(items: T[], page: number, pageSize: number): T[] {
  if (pageSize <= 0) return []
  const start = Math.max(0, (page - 1) * pageSize)
  return items.slice(start, start + pageSize)
}

/** 总页数（至少 1 页 —— 空列表也要有「1/1」而不是「0/0」）。 */
export function totalPages(total: number, pageSize: number): number {
  if (pageSize <= 0) return 1
  return Math.max(1, Math.ceil(total / pageSize))
}

/** 记录在筛选结果里的序号（找不到返回 -1）。 */
export function indexOfRow(rows: EvaluationRow[], selected: RecordKey | undefined): number {
  if (!selected) return -1
  return rows.findIndex((row) => isSelectedRow(row, selected))
}
