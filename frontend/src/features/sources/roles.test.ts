/**
 * 列 → 指标的字段指派。
 */

import { describe, expect, it } from 'vitest'
import { normalizeTimeFormat, resolveRoles, roleOf } from './roles'
import type { SourceQueryColumn } from '../../api/types'

const COLUMNS: SourceQueryColumn[] = [
  { name: 'observed_at', type: 'TIMESTAMP' },
  { name: 'metric_value', type: 'REAL' },
  { name: 'ts_epoch', type: 'INTEGER' },
  { name: 'host', type: 'TEXT' },
]

describe('resolveRoles', () => {
  it('没指派时按类型推断', () => {
    const roles = resolveRoles(COLUMNS, {})
    expect(roles.time_column).toBe('observed_at')
    expect(roles.value_column).toBe('metric_value')
  })

  it('用户指派优先于自动推断', () => {
    const roles = resolveRoles(COLUMNS, { observed_at: 'group' })
    expect(roles.group_column).toBe('observed_at')
    // ⚠️ 被显式指派走的列不再参与自动推断 —— 时间列让位
    expect(roles.time_column).toBeUndefined()
  })

  it('一个角色只能属于一列', () => {
    const roles = resolveRoles(COLUMNS, { observed_at: 'value', metric_value: 'value' })
    expect(roles.value_column).toBe('metric_value')
  })

  it('选了「不使用」的列不参与推断', () => {
    const roles = resolveRoles(COLUMNS, { observed_at: 'none' })
    expect(roles.time_column).toBeUndefined()
  })

  it('⚠️ epoch 存的整数时间列（名字像 ts）判成时间列，不是值列', () => {
    /* ⚠️ **epoch 时间列是 INTEGER** —— 只看 dtype 的话它会被判成「值列」，
       于是 `ts` 抢走值列的角色、真正的 `value` 反而「不使用」，完全反了。 */
    const roles = resolveRoles(
      [
        { name: 'ts', type: 'INTEGER' },
        { name: 'value', type: 'REAL' },
      ],
      {},
    )
    expect(roles.time_column).toBe('ts')
    expect(roles.value_column).toBe('value')
  })

  it('名字不像时间列的 INTEGER 仍然是值列', () => {
    // ⚠️ 名字匹配是**精确匹配** —— `ts_epoch` 不算时间列
    const roles = resolveRoles(
      [
        { name: 'ts_epoch', type: 'INTEGER' },
        { name: 'metric_value', type: 'REAL' },
      ],
      {},
    )
    expect(roles.time_column).toBeUndefined()
    // ⚠️ 两个数值列 → 列顺序里第一个赢（推断的固有局限，可在下拉里改）
    expect(roles.value_column).toBe('ts_epoch')
  })

  it('两个数值列时，列顺序里第一个当值列', () => {
    /* ⚠️ 这是推断的固有局限 —— 靠列顺序猜。
       用户可以在列头下拉里改。 */
    const roles = resolveRoles(
      [
        { name: 'ts', type: 'TIMESTAMP' },
        { name: 'value', type: 'REAL' },
        { name: 'doubled', type: 'REAL' },
      ],
      {},
    )
    expect(roles.value_column).toBe('value')
  })
})

describe('roleOf', () => {
  it('报出某一列当前扮演的角色', () => {
    expect(roleOf(COLUMNS, {}, 'observed_at')).toBe('time')
    expect(roleOf(COLUMNS, {}, 'metric_value')).toBe('value')
    expect(roleOf(COLUMNS, {}, 'host')).toBe('none')
  })
})

describe('normalizeTimeFormat', () => {
  it('时间列是 INTEGER 时改用 epoch —— iso 会静默落到 1970 年', () => {
    expect(normalizeTimeFormat(COLUMNS, 'ts_epoch', 'iso_utc')).toBe('epoch_s')
  })

  it('已经选了 epoch 就别动它（epoch_s 还是 epoch_ms 得看源）', () => {
    expect(normalizeTimeFormat(COLUMNS, 'ts_epoch', 'epoch_ms')).toBe('epoch_ms')
  })

  it('时间列不是 INTEGER 就保持原样', () => {
    expect(normalizeTimeFormat(COLUMNS, 'observed_at', 'iso_utc')).toBe('iso_utc')
  })

  it('没有时间列就保持原样', () => {
    expect(normalizeTimeFormat(COLUMNS, undefined, 'iso_utc')).toBe('iso_utc')
  })
})
