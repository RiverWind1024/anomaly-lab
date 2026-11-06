/**
 * 告警方向 → 中文标签。
 *
 * ⚠️ 界面上一律用中文 —— 原始值 `both` / `above` / `below`
 *    是内部标识，显示给用户等于让人看代码。
 */
import type { AlertDirection } from '../api/types'

/** 下拉选项（「双向」带「默认」提示，帮用户知道不选时会发生什么）。 */
export const ALERT_DIRECTION_OPTIONS: Array<{
  value: AlertDirection
  label: string
}> = [
  { value: 'both', label: '双向（默认）' },
  { value: 'above', label: '只报偏高' },
  { value: 'below', label: '只报偏低' },
]
