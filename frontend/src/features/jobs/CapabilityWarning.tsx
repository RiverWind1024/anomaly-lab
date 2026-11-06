import { Alert } from 'antd'
import type { Capability } from '../../api/types'

export interface CapabilityWarningProps {
  /** 当前序列实际用的算法（`auto` 会落到具体算法上）。 */
  detector: string
  capability: Pick<Capability, 'verdict' | 'warnings' | 'count_ready'> | null | undefined
  /** 当前检测器的首选尺度（iqr / mad / std），来自 series entry。 */
  preferScale?: string
  /** 本次是否真的发生了尺度降级。 */
  scaleFallback?: boolean
}

/** 只有它们要求「非负整数计数」。 */
const COUNT_ALGORITHMS = new Set(['poisson_count', 'event_count'])

/**
 * 「这个指标会让当前算法失效」的提示。
 *
 * ⚠️ 只提示**当前算法**那条 —— 能力探测会同时给出 iqr / mad / zscore 的结论，
 *    全列出来会让用户以为三条都跟当前这次检测有关。
 */
export function CapabilityWarning({
  detector,
  capability,
  preferScale,
  scaleFallback,
}: CapabilityWarningProps) {
  if (!capability) return null

  const hit =
    capability.verdict === 'ok'
      ? undefined
      : (capability.warnings ?? []).find(
          (w) =>
            w.detector === detector ||
            // ⚠️ 尺度族警告（iqr/mad 失效）要能命中「复用这一族尺度」的算法：
            //    seasonal / stl_residual 用 mad，trend_residual_iqr 用 iqr。
            //    但只有真的降级了才算 —— STL 在零膨胀原始值上 residual MAD 仍有效，
            //    按族名硬匹配会反过来误报。
            (scaleFallback === true && preferScale && w.detector === preferScale),
        )
  if (hit) {
    return (
      <Alert
        type="warning"
        showIcon
        message={`当前算法在这个指标上不可靠：${hit.reason}`}
        description="这类数据不符合该算法的假设：能跑，但结果不可靠，可能漏报也可能误报。"
        style={{ marginBottom: 12 }}
      />
    )
  }

  // ⚠️ 计数类算法的前提不在 warnings 里 —— 连续值数据本身「没病」，
  //    只是不适配这两个算法。所以单独按「算法 × 数据形态」判断，
  //    不去动 warnings / verdict，避免所有连续值序列被判成 unsuitable。
  const countMismatch =
    COUNT_ALGORITHMS.has(detector) && capability.count_ready === false
  if (countMismatch) {
    return (
      <Alert
        type="warning"
        showIcon
        message="当前算法要求非负整数计数，这份数据不是"
        description="泊松 / 事件计数类算法只适用于非负整数计数（如每分钟 error 数、重试数）：能跑，但结果没有意义。"
        style={{ marginBottom: 12 }}
      />
    )
  }

  return null
}
