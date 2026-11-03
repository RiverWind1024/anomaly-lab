/**
 * 分类色板 —— 多序列图表的线条颜色。
 *
 * 来自 tokens.css 的 `--series-1..5`（单一视觉来源）。
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
