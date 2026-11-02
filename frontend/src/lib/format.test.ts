import { describe, expect, it } from 'vitest'
import { fmtMetric } from './format'

describe('fmtMetric', () => {
  it('保留三位小数', () => {
    expect(fmtMetric(0.5)).toBe('0.500')
  })

  it('非有限值显示「—」', () => {
    expect(fmtMetric(NaN)).toBe('—')
    expect(fmtMetric(null)).toBe('—')
    expect(fmtMetric(undefined)).toBe('—')
  })
})
