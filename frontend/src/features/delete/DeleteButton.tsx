import { Button, Popconfirm } from 'antd'
import type { Catalog } from '../../api/types'
import { impactText, type DeleteTarget } from './impact'

export interface DeleteButtonProps {
  target: DeleteTarget
  id: number
  name: string
  catalog: Catalog | undefined
  onConfirm: () => void
  loading?: boolean
}

const NOUN: Record<DeleteTarget, string> = {
  source: '数据源',
  metric: '指标',
  job: '任务',
}

/**
 * 删除按钮。
 *
 * ⚠️ 确认文案必须**具体**（「将连带删除 2 个指标、3 个任务」）——
 *    笼统的「确定吗」会让用户误判影响范围。
 */
export function DeleteButton({
  target,
  id,
  name,
  catalog,
  onConfirm,
  loading,
}: DeleteButtonProps) {
  const impact = catalog ? impactText(target, id, catalog) : '将删除该对象'
  return (
    <Popconfirm
      title={`确定删除${NOUN[target]}「${name}」？`}
      description={impact}
      okText="删除"
      cancelText="取消"
      okButtonProps={{ danger: true }}
      onConfirm={onConfirm}
    >
      <Button size="small" danger loading={loading}>
        删除
      </Button>
    </Popconfirm>
  )
}
