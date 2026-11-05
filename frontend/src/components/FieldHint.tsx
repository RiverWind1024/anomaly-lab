import type { ReactNode } from 'react'
import { Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'

export interface FieldHintProps {
  label: ReactNode
  /** 说明文字 —— 悬停问号才看得到。 */
  hint: string
}

/**
 * 表单字段的说明 —— 收进 label 右侧的问号图标。
 *
 * ⚠️ **为什么不在字段下面挂一行小字**：
 *   - 那一行灰色字把表单撑高，却大部分人根本不读；
 *   - 真正会因此做错事的说明（比如「$timefilter 原样提交」）才有价值，
 *     其余都是噪音；
 *   - 需要的人悬停就能看，不需要的人眼前干净。
 *
 * 用法：
 * ```tsx
 * <Form.Item name="group_column" label={hint('分组列', '填了会按这一列拆成多条序列')}>
 * ```
 */
export function FieldHint({ label, hint }: FieldHintProps) {
  return (
    <span className="field-hint">
      {label}
      <Tooltip title={hint}>
        <QuestionCircleOutlined className="field-hint__icon" />
      </Tooltip>
    </span>
  )
}

/** 便捷函数：给 label 挂一个说明。 */
export function hint(label: ReactNode, text: string): ReactNode {
  return <FieldHint label={label} hint={text} />
}
