/** 数值与时间格式化。 */

/**
 * 把指标数值格式化成三位小数的字符串。
 *
 * ⚠️ `null` / `undefined` / `NaN` 一律显示「—」——
 *    表格里出现 `NaN` 或 `undefined` 会让人以为程序坏了。
 */
export function fmtMetric(value: number | null | undefined): string {
  return Number.isFinite(value) ? Number(value).toFixed(3) : '—'
}

export type TimeInput = string | number | Date | null | undefined

/**
 * 解析后端给的时间戳。
 *
 * ⚠️ 后端统一存 **UTC**，且大部分是无时区后缀的朴素文本
 *    （`2026-10-30T09:38:00`）。直接 `Date.parse` 会按浏览器时区解释 ——
 *    东八区就平白少算了 8 小时。所以没有时区后缀时补一个 `Z`。
 */
export function parseTs(ts: string): number {
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(ts)) return Date.parse(ts)
  return Date.parse(ts + 'Z')
}

/** 时间输入 → Date；非法值返回 null（调用方统一显示「—」）。 */
function toDate(value: TimeInput): Date | null {
  if (value === null || value === undefined || value === '') return null
  const ms =
    value instanceof Date ? value.getTime() : typeof value === 'number' ? value : parseTs(value)
  if (!Number.isFinite(ms)) return null
  const date = new Date(ms)
  return Number.isNaN(date.getTime()) ? null : date
}

function pad2(n: number): string {
  return n < 10 ? '0' + n : String(n)
}

/**
 * 后端时间 → `11-06 19:38`（**浏览器本地时区**）。
 *
 * ⚠️ 显示层一律走本地时区，存储与接口仍是 UTC ——
 *    北京时间用户看到的就不会是「凌晨 3 点的告警」了。
 */
export function fmtDateTime(ts: TimeInput): string {
  const d = toDate(ts)
  if (!d) return '—'
  return (
    pad2(d.getMonth() + 1) +
    '-' +
    pad2(d.getDate()) +
    ' ' +
    pad2(d.getHours()) +
    ':' +
    pad2(d.getMinutes())
  )
}

/** 后端时间 → `11-06 19:38:05`（本地时区，精确到秒）。 */
export function fmtDateTimeSec(ts: TimeInput): string {
  const d = toDate(ts)
  if (!d) return '—'
  return fmtDateTime(ts) + ':' + pad2(d.getSeconds())
}

/** 后端时间 → `2026-11-06 19:38:05`（本地时区，带年份）。 */
export function fmtFullDateTime(ts: TimeInput): string {
  const d = toDate(ts)
  if (!d) return '—'
  return `${d.getFullYear()}-${fmtDateTimeSec(ts)}`
}

/** 后端时间 → `19:38`（本地时区）—— 图表横轴用。 */
export function fmtClock(ts: TimeInput): string {
  const d = toDate(ts)
  if (!d) return '—'
  return pad2(d.getHours()) + ':' + pad2(d.getMinutes())
}

/** 后端时间 → `2026-11-06`（本地时区）。 */
export function fmtDay(ts: TimeInput): string {
  const d = toDate(ts)
  if (!d) return '—'
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}
