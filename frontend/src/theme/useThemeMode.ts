import { useCallback, useLayoutEffect, useState } from 'react'

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'anomaly-lab-theme'

/**
 * 读出初始主题模式。
 *
 * 优先级：localStorage 偏好 → 系统偏好 → 默认 dark（design system `dashboard` 的原设）。
 */
function readInitialMode(): ThemeMode {
  if (typeof window === 'undefined') return 'dark'
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    /* localStorage 不可用（隐私模式等），继续往下 */
  }
  if (window.matchMedia?.('(prefers-color-scheme: light)').matches) return 'light'
  return 'dark'
}

/**
 * 主题模式（dark / light）。
 *
 * 与 `tokens.css` 的 `[data-theme='light']` 覆盖块联动：
 * 切换时把 `data-theme` 写到 `<html>` 上，CSS 变量随之改变。
 *
 * ⚠️ **写入必须同步发生在渲染前** —— AntD 的 theme token 是运行时从 CSS 变量
 *    读出来的**实际色值**（见 theme/antdTheme.ts）。若读的时候 `<html>` 上还是
 *    旧主题，AntD 就会用另一套色值渲染。
 *
 *    所以这里用 `useState` 的**初始化函数**同步写 DOM：
 *    React 首次渲染时这个函数在 render 阶段就执行完了，
 *    早于 ConfigProvider 读色值。
 */
export function useThemeMode(): [ThemeMode, () => void] {
  const [mode, setMode] = useState<ThemeMode>(() => {
    const initial = readInitialMode()
    // 同步写 DOM —— 必须在 AntD 读 CSS 变量之前
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-theme', initial)
    }
    return initial
  })

  const toggle = useCallback(() => {
    setMode((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark'
      // state 更新是异步的，但 DOM 必须**立刻**改 ——
      // 否则这一轮渲染里 AntD 读到的还是旧主题的色值。
      document.documentElement.setAttribute('data-theme', next)
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        /* 忽略写入失败 */
      }
      return next
    })
  }, [])

  // 挂载后再补一次持久化（首屏的 localStorage 写入）
  useLayoutEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      /* 忽略写入失败 */
    }
  }, [mode])

  return [mode, toggle]
}
