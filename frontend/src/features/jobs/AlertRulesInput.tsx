import { useMemo } from 'react'
import { Alert, Input } from 'antd'
import type { AlertRule } from '../../api/types'
import { parseRules } from './rules'

export interface AlertRulesInputProps {
  value: AlertRule[]
  onChange: (rules: AlertRule[]) => void
  /** 外部持有的纯文本（受控）。留空则组件内部维护 —— 这里由父组件持有，便于与算法联动预填。 */
  text: string
  onTextChange: (text: string) => void
}

/**
 * 告警规则输入。
 *
 * 每行一条 `条件, 等级`。条件可以是：
 *   - 倍数：`2.5`（必须 > 0）
 *   - 绝对值：`>50` / `>=50` / `<10` / `<=10`
 *
 * ⚠️ 非法行**不静默丢弃** —— 显示行内错误，且整体不提交。
 *    旧版这里用 alert 弹窗打断输入（spec §8.2-B 要修掉的缺陷之一）。
 */
export function AlertRulesInput({ onChange, text, onTextChange }: AlertRulesInputProps) {
  const { rules, errors } = useMemo(() => parseRules(text), [text])
  const errorList = Object.entries(errors)

  const handleChange = (next: string) => {
    onTextChange(next)
    // 文本合法时把规则同步出去；不合法时保留上一次的合法值（不提交）
    const parsed = parseRules(next)
    if (parsed.rules) onChange(parsed.rules)
  }

  return (
    <div className="rules-input">
      <Input.TextArea
        value={text}
        onChange={(e) => handleChange(e.target.value)}
        rows={4}
        placeholder={'每行一条「条件, 等级」\n例：\n2.5, P1\n>50, P0'}
        spellCheck={false}
      />
      {errorList.length > 0 ? (
        <Alert
          type="error"
          showIcon
          className="rules-input__errors"
          message="告警规则有误，提交已被拦下"
          description={
            <ul className="rules-input__error-list">
              {errorList.map(([lineNo, message]) => (
                <li key={lineNo}>{message}</li>
              ))}
            </ul>
          }
        />
      ) : (
        <p className="muted rules-input__hint">
          从上到下按严重程度排列（最后一行最严重），命中多条时取最高档。
          倍数条件是主判定；<code>&gt;50</code> 这类绝对值条件并行生效，只能抬高等级、不会压低分数判定。
          留空则用默认两档（缩放因子 2.5 → P1，3.75 → P0）。
        </p>
      )}
      {/* 已解析出的规则条数 —— 让用户看到「填了但没生效」之外的情况 */}
      {errorList.length === 0 && rules && rules.length > 0 && (
        <p className="muted rules-input__parsed">已识别 {rules.length} 条规则。</p>
      )}
    </div>
  )
}
