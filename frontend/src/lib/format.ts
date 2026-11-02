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
