import { Alert } from 'antd'
import type { Capability } from '../../api/types'

export interface CapabilityWarningProps {
  /** 当前序列实际用的算法（`auto` 会落到具体算法上）。 */
  detector: string
  capability: Pick<Capability, 'verdict' | 'warnings'> | null | undefined
}

/**
 * 「这个指标会让当前算法失效」的提示。
 *
 * ⚠️ 只提示**当前算法**那条 —— 能力探测会同时给出 iqr / mad / zscore 的结论，
 *    全列出来会让用户以为三条都跟当前这次检测有关。
 *    `auto` 是逐序列选算法的，此时把全部结论合成一条。
 */
export function CapabilityWarning({ detector, capability }: CapabilityWarningProps) {
  if (!capability || capability.verdict === 'ok') return null
  const hits =
    detector === 'auto'
      ? capability.warnings
      : capability.warnings.filter((item) => item.detector === detector)
  if (hits.length === 0) return null
  return (
    <Alert
      type="warning"
      showIcon
      message={`当前算法在这个指标上不可靠：${hits.map((item) => item.reason).join('；')}`}
      description="它会退回标准差兜底：能跑，但对这类数据不稳健，容易漏报或误报。"
      style={{ marginBottom: 12 }}
    />
  )
}
