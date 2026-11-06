/**
 * 告警方向的展示与表单逻辑。
 *
 * ⚠️ 界面上一律用中文 —— 原始值 `both` / `above` / `below`
 *    是内部标识，显示给用户等于让人看代码。
 *
 * ⚠️ 这段逻辑两个入口共用（新建任务 / 任务配置），
 *    复制两份迟早会一边改了另一边忘掉。
 */
import type { AlertDirection } from '../api/types'

/** 算法没有基线时，只能报偏高 —— 不准选「只报偏低」。 */
export function detectorSupportsBelow(
  direction: 'both' | 'above' | undefined,
): boolean {
  return (direction ?? 'both') === 'both'
}

/** 方向下拉的选项。没有基线的算法把「只报偏低」禁用。 */
export function directionOptions(direction: 'both' | 'above' | undefined) {
  return [
    { value: 'both' as const, label: '双向（默认）' },
    { value: 'above' as const, label: '只报偏高' },
    {
      value: 'below' as const,
      label: '只报偏低',
      disabled: !detectorSupportsBelow(direction),
    },
  ]
}

/** 表单里那句说明，两个入口共用。 */
export function directionHint(
  direction: 'both' | 'above' | undefined,
): string {
  return detectorSupportsBelow(direction)
    ? '「双向」两侧都报；「只报偏高」忽略向下偏离；「只报偏低」忽略向上偏离。'
    : '当前算法没有基线，只能报「偏高」的异常。'
}

/** 切到无基线算法时，把已经选中的「只报偏低」改回双向。 */
export function normalizeDirection(
  current: AlertDirection | undefined,
  direction: 'both' | 'above' | undefined,
): AlertDirection {
  if (!detectorSupportsBelow(direction) && current === 'below') return 'both'
  return current ?? 'both'
}
