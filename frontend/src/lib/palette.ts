/**
 * 分类色板 —— 多序列图表的线条颜色。
 *
 * 来自 tokens.css 的 `--series-1..6`（单一视觉来源）。
 *
 * ⚠️ 旧代码的 `COMPARE_COLORS` 里 `#d97706` 与 P1 告警色撞色 ——
 *    `--series-*` 已按 D17 解出与告警三档色相错开 ≥35°。
 *
 * ⚠️ 放这里而不是某个 feature 里 —— 对比图与浏览预览图都要用，
 *    颜色得是同一个来源。
 */

import { cssVar } from '../theme/cssVar'

/** 调色板（按顺序取，超出就循环）。 */
export function seriesColors(): string[] {
  return [
    cssVar('--series-1', '#7acd51'),
    cssVar('--series-2', '#81c4da'),
    cssVar('--series-3', '#6161d1'),
    cssVar('--series-4', '#c079d8'),
    cssVar('--series-5', '#ca4994'),
    cssVar('--series-6', '#4fc7a1'),
  ]
}

/**
 * 取第 n 个序列的颜色。
 *
 * ⚠️ 超出调色板长度就**循环** —— 宁可颜色重复，也不要一半的线没颜色。
 */
export function seriesColor(index: number): string {
  const colors = seriesColors()
  return colors[index % colors.length]
}

/**
 * 第 n 个序列的**线型**。
 *
 * ⚠️ 为什么需要：色板只有 6 色，而假远端有 7 条序列 ——
 *    第 7 条会和第 1 条**同色**，读图时分不清哪条是哪条。
 *
 * ⚠️ 在保持「与告警三档色相错开 ≥35°」的前提下，
 *    算得出来的**空色相段只有 135°~160° 一个** ——
 *    加不到 7 个互不撞色的分类色。
 *
 *    所以超出部分用**虚线**区分：颜色循环 + 线型分段。
 */
export function seriesDashed(index: number): boolean {
  const count = seriesColors().length
  return Math.floor(index / count) % 2 === 1
}
