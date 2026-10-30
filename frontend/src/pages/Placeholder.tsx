import type { ReactNode } from 'react'

/**
 * 路由占位页。Task 7 起逐个替换成真页面。
 *
 * 故意做成「像那么回事」的样子 —— 骨架阶段就要能看出侧边栏/主题/间距是否对，
 * 而不是等到真页面写完才发现布局要重做。
 */
export function Placeholder({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="placeholder">
      <h1 className="placeholder__title">{title}</h1>
      {hint && <p className="placeholder__hint">{hint}</p>}
      <p className="muted">该页面将在后续阶段实现。</p>
    </div>
  )
}
