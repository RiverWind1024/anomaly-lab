/** 数值格式化：非有限值显示「—」（旧版 report.js 的 fmt）。 */

/**
 * 把指标数值格式化成三位小数的字符串。
 *
 * ⚠️ `null` / `undefined` / `NaN` 一律显示「—」——
 *    表格里出现 `NaN` 或 `undefined` 会让人以为程序坏了。
 */
export function fmtMetric(value: number | null | undefined): string {
  return Number.isFinite(value) ? Number(value).toFixed(3) : '—'
}

/**
 * 解析后端给的时间戳。
 *
 * ⚠️ 后端给的是**不带时区的 UTC 文本**（`2026-10-30T09:38:00`），
 *    直接 `Date.parse` 会按本地时区解析 —— 东八区就差了 8 小时。
 *    所以没有时区后缀时补一个 `Z`。
 */
export function parseTs(ts: string): number {
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(ts)) return Date.parse(ts)
  return Date.parse(ts + 'Z')
}

function pad2(n: number): string {
  return n < 10 ? '0' + n : String(n)
}

/** `2026-10-30T09:38:00` → `10-30 09:38`（UTC）。 */
export function fmtUtcTime(ts: string | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(parseTs(ts))
  if (Number.isNaN(d.getTime())) return '—'
  return (
    pad2(d.getUTCMonth() + 1) +
    '-' +
    pad2(d.getUTCDate()) +
    ' ' +
    pad2(d.getUTCHours()) +
    ':' +
    pad2(d.getUTCMinutes())
  )
}

/** `2026-10-30T09:38:00` → `10-30 09:38:00`（UTC，精确到秒）。 */
export function fmtUtcSeconds(ts: string | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(parseTs(ts))
  if (Number.isNaN(d.getTime())) return '—'
  return (
    pad2(d.getUTCMonth() + 1) +
    '-' +
    pad2(d.getUTCDate()) +
    ' ' +
    pad2(d.getUTCHours()) +
    ':' +
    pad2(d.getUTCMinutes()) +
    ':' +
    pad2(d.getUTCSeconds())
  )
}
