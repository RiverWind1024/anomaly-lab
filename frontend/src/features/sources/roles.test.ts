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
