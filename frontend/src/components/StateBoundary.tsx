import { Alert, Skeleton } from 'antd'
import type { ReactNode } from 'react'
import { ApiError, type BizState } from '../api/client'

export interface StateBoundaryProps<T> {
  isLoading: boolean
  error: unknown
  data: T | undefined
  /** 数据为空时的判定；返回 false 说明有数据 */
  isEmpty?: (data: T) => boolean
  emptyTitle?: string
  emptyHint?: string
  /** 空态按钮（如「立即运行」） */
  emptyAction?: ReactNode
  /** 数据不足态：返回原因字符串则进入「数据不足」态（不是错误态） */
  insufficient?: (data: T) => string | null
  /** 业务态（bizState）对应的空态标题；缺省用统一文案 */
  bizTitles?: Partial<Record<BizState, string>>
  children: (data: T) => ReactNode
}

/** 业务态 → 默认空态标题 */
const BIZ_DEFAULT_TITLES: Record<BizState, string> = {
  no_run: '该任务还没有运行记录',
  no_series: '该次运行没有序列结果',
  no_data: '该窗口内没有取到数据',
  insufficient_data: '数据不足',
  no_algorithms: '没有可对比的算法',
  no_result: '还没有可查看的 Bad Case',
}

/**
 * 五态边界：加载 / 空 / 错误 / 数据不足 / 正常。
 *
 * ⚠️ **`bizState` 必须在这里被消费** —— 后端加 `X-Anomaly-Biz-State` 响应头的
 * 全部意义就在于此：业务态要走空态/数据不足态，**不能显示红色错误框**。
 */
export function StateBoundary<T>(props: StateBoundaryProps<T>) {
  const {
    isLoading, error, data, isEmpty, emptyTitle, emptyHint, emptyAction,
    insufficient, bizTitles, children,
  } = props

  if (isLoading) return <Skeleton active paragraph={{ rows: 6 }} />

  if (error) {
    const apiErr = error instanceof ApiError ? error : null
    const biz = apiErr?.bizState
    if (biz === 'insufficient_data') {
      // 数据不足是业务态，不是错误态 —— 用 warning 而不是 error
      return <Alert type="warning" showIcon message="数据不足" description={apiErr?.message} />
    }
    if (biz) {
      const title = bizTitles?.[biz] ?? BIZ_DEFAULT_TITLES[biz]
      return (
        <div className="empty-state">
          <p className="empty-state__title">{title}</p>
          {/* ⚠️ 后端的 detail 文案常常与标题一字不差（如 no_run）， taste-skill-ignore
              重复渲染会出现两个同样的文本 —— 相同时只渲染标题。 */}
          {apiErr?.message && apiErr.message !== title && (
            <p className="muted">{apiErr.message}</p>
          )}
          {emptyAction}
        </div>
      )
    }
    return <ErrorPanel error={error} />
  }

  if (data === undefined) return null

  const reason = insufficient?.(data)
  if (reason) {
    return <Alert type="warning" showIcon message="数据不足" description={reason} />
  }

  if (isEmpty?.(data)) {
    return (
      <div className="empty-state">
        <p className="empty-state__title">{emptyTitle ?? '暂无数据'}</p>
        {emptyHint && <p className="muted">{emptyHint}</p>}
        {emptyAction}
      </div>
    )
  }

  return <>{children(data)}</>
}

function ErrorPanel({ error }: { error: unknown }) {
  const message = error instanceof ApiError ? error.message : '请求失败'
  const status = error instanceof ApiError ? error.status : undefined
  return (
    <Alert
      type="error"
      showIcon
      message={status ? `请求失败（HTTP ${status}）` : '请求失败'}
      description={message}
    />
  )
}
