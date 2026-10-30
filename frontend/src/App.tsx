import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter } from 'react-router-dom'
import { useMemo } from 'react'
import { AppLayout } from './components/AppLayout'
import { AppRoutes } from './router'
import { buildAntdTheme } from './theme/antdTheme'
import { useThemeMode } from './theme/useThemeMode'

/**
 * 应用根。
 *
 * 包裹顺序：QueryClientProvider → ConfigProvider → BrowserRouter → AppLayout + Routes。
 *
 * ⚠️ `buildAntdTheme` 必须在 `data-theme` 写好之后调用 —— AntD 不吃 CSS 变量，
 *    要运行时读实际色值（见 theme/antdTheme.ts 的说明）。
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
        <AntApp>
          <BrowserRouter>
            <AppLayout themeMode={themeMode} onToggleTheme={toggleTheme}>
              <AppRoutes />
            </AppLayout>
          </BrowserRouter>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  )
}
