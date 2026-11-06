import type { ReactNode } from 'react'
import type { DecisionTraceData } from '../../api/types'
import { metricClassLabel } from '../jobs/ClassificationCard'
import './decisionTrace.css'

type StepKey = keyof DecisionTraceData

const STEPS: ReadonlyArray<readonly [StepKey, string]> = [
  ['quality', '数据质量'],
  ['capability', '能力探测'],
  ['classify', '形态判断'],
  ['select', '算法选择'],
  ['threshold', '阈值与分级'],
  ['detect', '结果'],
]

/** 每一步的一行人话摘要。缺字段时返回 null（整步不显示）。 */
function summary(key: StepKey, step: Record<string, unknown>): ReactNode {
  switch (key) {
    case 'quality':
      return `${step.n} 点 · 零值 ${(Number(step.zero_ratio) * 100).toFixed(1)}% · 缺 ${step.n_missing}`
    case 'capability': {
      if (step.verdict === 'ok') return '无失效风险'
      // ⚠️ Record<string, unknown> 下必须先收窄，否则 TS7053
      const warnings = Array.isArray(step.warnings) ? step.warnings : []
      const first = warnings[0] as { reason?: string } | undefined
      return first?.reason ?? String(step.verdict ?? '')
    }
    case 'classify': {
      const metricClass = typeof step.metric_class === 'string' ? step.metric_class : ''
      const confidence = Number(step.confidence ?? 0).toFixed(2)
      return metricClass
        ? `${metricClassLabel(metricClass)} / ${metricClass}（${confidence}）`
        : `—（${confidence}）`
    }
    case 'select':
      return `${String(step.requested ?? '')} → ${String(step.detector ?? '')}${step.fallback ? '（回退）' : ''}`
    case 'threshold':
      return `尺度 ${String(step.scale_source ?? '—')} · ${step.status === 'undetermined' ? '无法判定' : '正常'}`
    case 'detect':
      return `${step.n_alerts ?? 0} 个告警点 · ${step.n_p0 ?? 0} 条 P0`
    default:
      return null
  }
}

/** 异常路径高亮：能力不足 / 算法回退 / 尺度判不出来 / 退回标准差。 */
function isWarn(key: StepKey, step: Record<string, unknown>): boolean {
  if (key === 'capability') return step.verdict !== 'ok'
  if (key === 'select') return Boolean(step.fallback)
  if (key === 'threshold') return step.status === 'undetermined' || step.scale_source === 'std'
  return false
}

/**
 * 一次检测的决策链时间线：数据质量 → 能力探测 → 形态判断 → 算法选择 → 阈值与分级 → 结果。
 *
 * 每步只给一行摘要，原始数字收进 `<details>` —— 结论先看，细节按需展开。
 * `trace` 为空（老数据）时整块不渲染。
 */
export function DecisionTraceTimeline({ trace }: { trace: DecisionTraceData }) {
  if (STEPS.every(([key]) => !trace[key])) return null

  return (
    <ol className="decision-trace">
      {STEPS.map(([key, title], index) => {
        const step = trace[key] as Record<string, unknown> | undefined
        if (!step) return null
        return (
          <li
            key={key}
            className={`decision-trace__step${isWarn(key, step) ? ' decision-trace__step--warn' : ''}`}
          >
            {/* ⚠️ 序号按 STEPS 的原始位置算，不是过滤后的下标 ——
                老数据可能缺中间某段，缺一步不该让后面的编号全部前移 */}
            <span className="decision-trace__index" aria-hidden="true">
              {index + 1}
            </span>
            <strong>{title}</strong>
            <span className="decision-trace__summary">{summary(key, step)}</span>
            <details>
              <summary>原始数字</summary>
              <pre className="mono">{JSON.stringify(step, null, 2)}</pre>
            </details>
          </li>
        )
      })}
    </ol>
  )
}
