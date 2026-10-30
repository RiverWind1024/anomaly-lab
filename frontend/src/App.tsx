import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter } from 'react-router-dom'
import { useMemo } from 'react'
import { AppLayout } from './components/AppLayout'
import { AppRoutes } from './router'
import { buildAntdTheme } from './theme/antdTheme'
import { ThemeModeContext } from './theme/ThemeModeContext'
import { useThemeMode } from './theme/useThemeMode'

/**
 * 应用根。
 *
 * 包裹顺序：QueryClientProvider → ConfigProvider → BrowserRouter → AppLayout + Routes。
 *
 * ⚠️ `buildAntdTheme` 必须在 `data-theme` 写好之后调用 —— AntD 不吃 CSS 变量，
 *    要运行时读实际色值（见 theme/antdTheme.ts 的说明）。
 *
 * ⚠️ **刻意不用 antd 的 `App` 组件** —— 它会连带引入 message/modal/notification
 *    三个组件族，实测让 bundle 从 218 KB 涨到 396 KB（+178 KB）。
 *    我们用不到 `App.useApp()`，用 `message` 静态方法就够了。
 */
export function App() {
  const [themeMode, toggleTheme] = useThemeMode()
  const theme = useMemo(() => buildAntdTheme(themeMode), [themeMode])

  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // 监控平台的读多写少，默认不重取；显式失效由 mutation 触发
            refetchOnWindowFocus: false,
            retry: 1,
            staleTime: 10_000,
          },
        },
      }),
    [],
  )

  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN} theme={theme}>
        {/* 主题模式进 context —— ECharts 之类的库要靠它知道该重画了 */}
        <ThemeModeContext.Provider value={themeMode}>
          <BrowserRouter>
            <AppLayout themeMode={themeMode} onToggleTheme={toggleTheme}>
              <AppRoutes />
            </AppLayout>
          </BrowserRouter>
        </ThemeModeContext.Provider>
      </ConfigProvider>
    </QueryClientProvider>
  )
}
