import { Alert } from 'antd'
import type { Capability } from '../../api/types'

export interface CapabilityWarningProps {
  /** 当前序列实际用的算法（`auto` 会落到具体算法上）。 */
  detector: string
  capability: Pick<Capability, 'verdict' | 'warnings'> | null | undefined
  /** 当前检测器的首选尺度（iqr / mad / std），来自 series entry。 */
  preferScale?: string
  /** 本次是否真的发生了尺度降级。 */
  scaleFallback?: boolean
}

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
  if (!capability || capability.verdict === 'ok') return null
  const warnings = capability.warnings ?? []
  const hit = warnings.find(
    (w) =>
      w.detector === detector ||
      // ⚠️ 尺度族警告（iqr/mad 失效）要能命中「复用这一族尺度」的算法：
      //    seasonal / stl_residual 用 mad，trend_residual_iqr 用 iqr。
      //    但只有真的降级了才算 —— STL 在零膨胀原始值上 residual MAD 仍有效，
      //    按族名硬匹配会反过来误报。
      (scaleFallback === true && preferScale && w.detector === preferScale),
  )
  if (!hit) return null
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
