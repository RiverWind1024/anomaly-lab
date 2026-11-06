import { describe, expect, it } from 'vitest'
import {
  fmtClock,
  fmtDateTime,
  fmtDateTimeSec,
  fmtDay,
  fmtFullDateTime,
  fmtMetric,
} from './format'

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

/**
 * 时间显示必须按**浏览器本地时区**渲染。
 *
 * ⚠️ 测试时区由 `vite.config.ts` 的 `test.env.TZ` 固定为 Asia/Shanghai；
 *    否则 CI 跑在 UTC 机器上会「测试通过但用户看到的是 UTC」。
 */
describe('fmtDateTime 等本地时间格式化', () => {
  it('不带时区的后端文本按 UTC 解析，显示成本地时间', () => {
    // 11:53 UTC → 北京 19:53
    expect(fmtDateTime('2026-11-06T11:53:00')).toBe('11-06 19:53')
    expect(fmtDateTime('2026-11-06 11:53:00')).toBe('11-06 19:53')
  })

  it('已经带 +00:00 的时间戳同样换算', () => {
    expect(fmtDateTimeSec('2026-11-06T11:53:05+00:00')).toBe('11-06 19:53:05')
    expect(fmtFullDateTime('2026-11-06T11:53:05+00:00')).toBe('2026-11-06 19:53:05')
  })

  it('跨日会跟着日期一起变', () => {
    // 22:30 UTC → 次日 06:30（北京）
    expect(fmtDateTime('2026-11-06T22:30:00')).toBe('11-07 06:30')
    expect(fmtDay('2026-11-06T22:30:00')).toBe('2026-11-07')
  })

  it('横轴只取时分', () => {
    expect(fmtClock('2026-11-06T11:53:00')).toBe('19:53')
  })

  it('数字毫秒与 Date 也能吃', () => {
    const ms = Date.parse('2026-11-06T11:53:00Z')
    expect(fmtClock(ms)).toBe('19:53')
    expect(fmtClock(new Date(ms))).toBe('19:53')
  })

  it('空值 / 非法值显示「—」', () => {
    expect(fmtDateTime(null)).toBe('—')
    expect(fmtDateTime(undefined)).toBe('—')
    expect(fmtDateTime('')).toBe('—')
    expect(fmtDateTime('not-a-time')).toBe('—')
  })
})
