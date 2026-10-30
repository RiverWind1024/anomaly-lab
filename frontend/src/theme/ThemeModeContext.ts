import { createContext, useContext } from 'react'

/**
 * 当前主题模式（dark / light）。
 *
 * 用途：**ECharts 等不认 CSS 变量的库**需要知道主题变了才能重建 option ——
 * 它们读到的实际色值是运行时从 CSS 变量取的，主题一变色值就变，
 * 但库本身不会自动重画。
 */
export const ThemeModeContext = createContext<'dark' | 'light'>('dark')

export function useThemeModeValue(): 'dark' | 'light' {
  return useContext(ThemeModeContext)
}
