import { Space, Tag } from 'antd'
import type { AlertRule } from '../../api/types'

export interface AlertRulesViewProps {
  rules: AlertRule[] | null | undefined
  /** 是否显示「没有规则 → 用默认两档」的说明 */
  showDefaultHint?: boolean
}

/**
 * 告警规则**只读**展示。
 *
 * ⚠️ 后端没有「自由编辑告警规则」的端点（PATCH 只接受 enabled 与 detector，
 *    见 spec §8.3）—— 所以这里是只读的，规则只能在新建任务时录入。
 */
export function AlertRulesView({ rules, showDefaultHint = true }: AlertRulesViewProps) {
  if (!rules?.length) {
    return (
      <div className="alert-rules-view">
        <p className="muted">未设置告警规则</p>
        {showDefaultHint && (
          <p className="muted alert-rules-view__hint">
            使用默认两档（缩放因子 2.5 → P1，3.75 → P0）。规则只读 ——
            需要调整请新建任务。
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="alert-rules-view">
      <ul className="alert-rules-view__list">
        {rules.map((rule, index) => (
          <li key={index}>
            <Space size="small">
              <Tag color={levelColor(rule.level)}>{rule.level}</Tag>
              <span className="mono">
                {rule.multiplier == null
                  ? `${rule.op} ${rule.value}`
                  : `× ${rule.multiplier}`}
              </span>
            </Space>
          </li>
        ))}
      </ul>
      <p className="muted alert-rules-view__hint">
        从上到下按严重程度排列，命中多条时取最高档。规则只读 ——
        需要调整请新建任务。
      </p>
    </div>
  )
}

/** 档位名 → 颜色。P0/P1 用告警语义色，其余用中性色。 */
function levelColor(level: string): string {
  if (level === 'P0') return 'error'
  if (level === 'P1') return 'warning'
  return 'default'
}

/** 没有规则时的占位（用于表格单元格等场景）。 */
export function AlertRulesInline({ rules }: { rules: AlertRule[] | null | undefined }) {
  if (!rules?.length) return <span className="muted">默认两档</span>
  return (
    <span className="mono">
      {rules
        .map((r) =>
          r.multiplier == null ? `${r.op}${r.value}→${r.level}` : `${r.multiplier}×→${r.level}`,
        )
        .join(' / ')}
    </span>
  )
}
