import { describe, expect, it } from 'vitest'
import { FREQ_EXAMPLES, freqValidator, isValidFreq } from './freq'

describe('指标频率的格式校验', () => {
  it('接受后端 timeutil.freq_delta 支持的写法', () => {
    // 后端正则：^(\d+)(s|min|m|h|d)$，先 strip().lower()
    for (const value of ['5min', '1h', '1d', '1s', '30m', '1MIN', '  10min  ']) {
      expect(isValidFreq(value)).toBe(true)
    }
  })

  it('拒绝格式不对的写法', () => {
    for (const value of ['', '5', 'min', '5x', '5 min x', 'abc', '1.5min']) {
      expect(isValidFreq(value)).toBe(false)
    }
  })

  it('拒绝 0 —— 后端也要求频率为正', () => {
    expect(isValidFreq('0min')).toBe(false)
    expect(isValidFreq('0s')).toBe(false)
  })

  it('示例值都必须是合法频率', () => {
    for (const value of FREQ_EXAMPLES) {
      expect(isValidFreq(value)).toBe(true)
    }
  })
})

describe('freqValidator', () => {
  it('合法值放行', async () => {
    await expect(freqValidator(null, '5min')).resolves.toBeUndefined()
  })

  it('空值放行 —— 交给 required 规则处理', async () => {
    await expect(freqValidator(null, '')).resolves.toBeUndefined()
    await expect(freqValidator(null, undefined)).resolves.toBeUndefined()
  })

  it('非法值给出可读的错误', async () => {
    await expect(freqValidator(null, '5分钟')).rejects.toThrow(/频率格式/)
  })
})
