/**
 * 表单里的数值下限/上限与单位换算。
 *
 * ⚠️ 窗口边界**来自后端**，前端只是提前提示：
 *   - `WINDOW_SECONDS_MIN` / `WINDOW_SECONDS_MAX` ← `platform/validation.py::validate_window_seconds`
 *   - `INTERVAL_SECONDS_MIN`                    ← `platform/validation.py::validate_interval_seconds`
 * 后端没有把限制暴露到 API，改那边时这里必须同步；
 * `tests/web/test_api_contract.py` 会读这个文件做交叉校验，漂移会红。
 */

export const WINDOW_SECONDS_MIN = 60
/** 365 天（365 * 86400）—— 与后端 `validate_window_seconds` 的上限一致。 */
export const WINDOW_SECONDS_MAX = 31_536_000
export const INTERVAL_SECONDS_MIN = 10
/** 检测点数下限：0 = 检测整个窗口。 */
export const DETECT_POINTS_MIN = 0

/** 时间窗口的单位 —— 后端统一存秒数。 */
export const WINDOW_UNIT_SECONDS = {
  minute: 60,
  hour: 3600,
  day: 86400,
} as const

export type WindowUnit = keyof typeof WINDOW_UNIT_SECONDS

export const WINDOW_UNIT_OPTIONS = [
  { value: 'minute', label: '分钟' },
  { value: 'hour', label: '小时' },
  { value: 'day', label: '天' },
]

/** 秒数 → 「数值 + 单位」；能被整天/整小时整除时优先用大单位。 */
export function splitWindow(seconds: number): {
  window_value: number
  window_unit: WindowUnit
} {
  if (Number.isFinite(seconds) && seconds > 0) {
    if (seconds % 86400 === 0) {
      return { window_value: seconds / 86400, window_unit: 'day' }
    }
    if (seconds % 3600 === 0) {
      return { window_value: seconds / 3600, window_unit: 'hour' }
    }
    return { window_value: Math.max(1, Math.round(seconds / 60)), window_unit: 'minute' }
  }
  return { window_value: 1, window_unit: 'day' }
}
