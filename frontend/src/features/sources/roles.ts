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

/**
 * 单列的自动推断角色。
 *
 * ⚠️ **名字像时间列的优先判** —— 不管它是 TEXT 还是 INTEGER。
 *
 * ⚠️ 为什么不能只看 dtype：**epoch 存的时间列是 INTEGER**（很常见），
 *    而 INTEGER 默认会被判成「值列」。于是
 *    `SELECT ts, value FROM t` 里的 `ts` 抢走了值列的角色、
 *    真正的 `value` 反而「不使用」—— **完全反了**，
 *    而且界面上看不出哪里不对（两个下拉都显示得出，只是不该是这样）。
 *
 * ⚠️ 名字匹配是**精确匹配**（`^ts$` 匹配不到 `ts_id` / `ts_epoch`）——
 *    所以误伤面很小：真叫 `ts` 却存着普通数字的列，本来就极罕见。
 */
export function inferRole(column: SourceQueryColumn): ColumnRole | undefined {
  // ⚠️ 名字优先 —— epoch 时间列是 INTEGER，靠 dtype 分不出来
  if (looksLikeTimeColumn(column.name)) return 'time'
  if (column.type === 'TIMESTAMP') return 'time'
  if (column.type === 'REAL' || column.type === 'INTEGER') return 'value'
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

/**
 * 时间格式要不要按 epoch 修正。
 *
 * ⚠️ INTEGER 的时间列是 **epoch 秒/毫秒**存的 —— 按 iso 解释会静默落到
 *    1970 年，不报错但结果全错。所以时间列是 INTEGER 时，格式必须是 epoch。
 *
 * @param columns 浏览结果的列
 * @param timeColumn 被指派为时间列的列名
 * @param timeFormat 当前选的时间格式
 */
export function normalizeTimeFormat(
  columns: SourceQueryColumn[],
  timeColumn: string | undefined,
  timeFormat: string,
): string {
  if (!timeColumn) return timeFormat
  const type = columns.find((col) => col.name === timeColumn)?.type
  if (type !== 'INTEGER') return timeFormat
  // ⚠️ 已经选了 epoch 就别动它（epoch_s 还是 epoch_ms 得看源）
  return timeFormat.startsWith('epoch') ? timeFormat : 'epoch_s'
}
