import { describe, expect, it } from 'vitest'
import { defaultRulesFor, formatRules, parseRules, rulesToText } from './rules'

describe('parseRules', () => {
  it('解析倍数条件', () => {
    const { rules, errors } = parseRules('2.5, P1\n4, P0')
    expect(rules).toEqual([
      { multiplier: 2.5, level: 'P1' },
      { multiplier: 4, level: 'P0' },
    ])
    expect(errors).toEqual({})
  })

  it('解析绝对值条件（>50 / >=50 / <10 / <=10）', () => {
    const { rules } = parseRules('>50, P0\n>=50, P1\n<10, P1\n<= 10, P1')
    expect(rules).toEqual([
      { op: '>', value: 50, level: 'P0' },
      { op: '>=', value: 50, level: 'P1' },
      { op: '<', value: 10, level: 'P1' },
      { op: '<=', value: 10, level: 'P1' },
    ])
  })

  it('倍数必须为正 —— 0 被拦下并给行内错误', () => {
    const { rules, errors } = parseRules('0, P1')
    expect(rules).toBeNull()
    expect(errors[1]).toContain('倍数必须大于 0')
  })

  it('负数倍数被拦下', () => {
    const { rules, errors } = parseRules('-1, P1')
    expect(rules).toBeNull()
    expect(errors[1]).toContain('倍数必须大于 0')
  })

  it('非数字条件被拦下', () => {
    const { rules, errors } = parseRules('abc, P1')
    expect(rules).toBeNull()
    expect(errors[1]).toContain('格式应为')
  })

  it('缺少等级被拦下', () => {
    const { rules, errors } = parseRules('2.5')
    expect(rules).toBeNull()
    expect(errors[1]).toContain('缺少等级')
  })

  it('错误行号是 1-based，且不静默丢弃其他行', () => {
    const { rules, errors } = parseRules('2.5, P1\n0, P1\n4, P0')
    expect(rules).toBeNull() // 有错就整体不提交
    expect(Object.keys(errors)).toEqual(['2'])
  })

  it('留空返回 null（后端用默认两档）', () => {
    expect(parseRules('').rules).toBeNull()
    expect(parseRules('   \n  ').rules).toBeNull()
    expect(parseRules('').errors).toEqual({})
  })

  it('等级里含逗号时拼回完整等级', () => {
    // 沿用旧 platform.js 的 rest.join(',') 行为
    const { rules } = parseRules('2.5, P1, P0')
    expect(rules).toEqual([{ multiplier: 2.5, level: 'P1, P0' }])
  })
})

describe('formatRules', () => {
  it('空规则显示 -', () => {
    expect(formatRules(null)).toBe('-')
    expect(formatRules([])).toBe('-')
    expect(formatRules(undefined)).toBe('-')
  })

  it('倍数与绝对值条件都能格式化', () => {
    expect(formatRules([{ multiplier: 2.5, level: 'P1' }])).toBe('2.5×→P1')
    expect(formatRules([{ op: '>', value: 50, level: 'P0' }])).toBe('>50→P0')
  })

  it('多条规则用 / 分隔', () => {
    expect(
      formatRules([
        { multiplier: 2.5, level: 'P1' },
        { multiplier: 4, level: 'P0' },
      ]),
    ).toBe('2.5×→P1 / 4×→P0')
  })
})

describe('rulesToText', () => {
  it('能还原成可编辑的文本', () => {
    const text = rulesToText([
      { multiplier: 2.5, level: 'P1' },
      { op: '>', value: 50, level: 'P0' },
    ])
    expect(text).toBe('2.5, P1\n> 50, P0')
  })

  it('空规则返回空串', () => {
    expect(rulesToText(null)).toBe('')
  })
})

describe('defaultRulesFor', () => {
  it('按默认阈值预填两档（P0 = 阈值 × 1.5）', () => {
    expect(defaultRulesFor(2.5)).toBe('2.5, P1\n3.75, P0')
    expect(defaultRulesFor(3)).toBe('3, P1\n4.50, P0')
  })

  it('预填的规则能被 parseRules 解析回来', () => {
    const { rules, errors } = parseRules(defaultRulesFor(2.5))
    expect(errors).toEqual({})
    expect(rules).toEqual([
      { multiplier: 2.5, level: 'P1' },
      { multiplier: 3.75, level: 'P0' },
    ])
  })
})
