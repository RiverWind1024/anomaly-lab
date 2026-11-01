import type { SourceQueryColumn } from '../../api/types'

/**
 * 浏览结果的「列 → 指标字段」指派。
 *
 * ⚠️ 目的是让用户**看得见**地决定哪一列是时间列、哪一列是值列 ——
 *    自动推断只是默认值，用户随时能改。
 */

/** 一列在指标里扮演的角色。 */
export type ColumnRole = 'time' | 'value' | 'group'

/** 用户可以给某一列指派什么 —— 'none' 是「不使用」。 */
export type RoleChoice = ColumnRole | 'none'

/** 角色 → 指标表单里的字段。 */
export interface ColumnRoles {
  time_column?: string
  value_column?: string
  group_column?: string
}

export const ROLE_OPTIONS: Array<{ value: RoleChoice; label: string }> = [
  { value: 'none', label: '不使用' },
  { value: 'time', label: '时间列' },
  { value: 'value', label: '值列' },
  { value: 'group', label: '分组列' },
]

/**
 * 名字像不像时间列。
 *
 * ⚠️ JSON / SQLite 里的时间列几乎都是 **TEXT**（pandas dtype 是 object），
 *    只按 TIMESTAMP 推断的话基本不触发 —— 靠列名补偿。
 */
const TIME_LIKE_NAME = /^(ts|time|timestamp|datetime|date|observed_at|observedat|event_time)$/i

export function looksLikeTimeColumn(name: string): boolean {
  return TIME_LIKE_NAME.test(name.trim())
}

/** 单列的自动推断角色。 */
export function inferRole(column: SourceQueryColumn): ColumnRole | undefined {
  if (column.type === 'TIMESTAMP') return 'time'
  if (column.type === 'REAL' || column.type === 'INTEGER') return 'value'
  if (column.type === 'TEXT' && looksLikeTimeColumn(column.name)) return 'time'
  return undefined
}

/**
 * 有效角色 = **用户指派优先**，没指派过的列用自动推断补。
 *
 * ⚠️ 一个角色只能属于一列 —— 用户把 B 指派成「时间列」时，
 *    A 的自动推断就该让位。
 * ⚠️ 用户明确选了「不使用」的列，不再参与自动推断。
 */
export function resolveRoles(
  columns: SourceQueryColumn[],
  assignments: Record<string, RoleChoice>,
): ColumnRoles {
  const roles: ColumnRoles = {}
  const assigned = new Set<string>()

  for (const column of columns) {
    const choice = assignments[column.name]
    if (choice === undefined) continue
    assigned.add(column.name)
    if (choice === 'none') continue
    if (choice === 'time') roles.time_column = column.name
    else if (choice === 'value') roles.value_column = column.name
    else roles.group_column = column.name
  }

  for (const column of columns) {
    if (assigned.has(column.name)) continue
    const role = inferRole(column)
    if (role === 'time' && !roles.time_column) roles.time_column = column.name
    else if (role === 'value' && !roles.value_column) roles.value_column = column.name
  }
  return roles
}

/** 某一列当前扮演的角色（给下拉框显示用）。 */
export function roleOf(
  columns: SourceQueryColumn[],
  assignments: Record<string, RoleChoice>,
  columnName: string,
): RoleChoice {
  const roles = resolveRoles(columns, assignments)
  if (roles.time_column === columnName) return 'time'
  if (roles.value_column === columnName) return 'value'
  if (roles.group_column === columnName) return 'group'
  return 'none'
}
