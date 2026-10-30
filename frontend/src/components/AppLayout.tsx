import { Button, Layout, Menu, theme as antdTheme } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import type { ThemeMode } from '../theme/useThemeMode'
import './AppLayout.css'

const { Sider, Content } = Layout

/** 侧边栏导航项。路径与 router.tsx 的路由表一一对应。 */
export const NAV_ITEMS = [
  { key: '/', label: '序列总览' },
  { key: '/sources', label: '数据源' },
  { key: '/metrics', label: '指标' },
  { key: '/jobs', label: '检测任务' },
  { key: '/alerts', label: '告警中心' },
  { key: '/evaluation', label: '评估报告' },
  { key: '/badcases', label: 'Bad Case' },
  { key: '/annotate', label: '标注' },
]

export interface AppLayoutProps {
  themeMode: ThemeMode
  onToggleTheme: () => void
  children: ReactNode
}

export function AppLayout({ themeMode, onToggleTheme, children }: AppLayoutProps) {
  const location = useLocation()
  const { token } = antdTheme.useToken()

  // 详情页 /jobs/3 的高亮要落在 /jobs 上
  const selectedKey =
    NAV_ITEMS.find((item) => item.key !== '/' && location.pathname.startsWith(item.key))?.key ??
    (location.pathname === '/' ? '/' : '')

  return (
    <Layout className="app-layout">
      {/* 侧栏跟随主题 —— AntD 的 Menu theme="dark" 是写死的，
          浅色主题下会变成「暗侧栏 + 亮内容」，不协调 */}
      <Sider width={232} className="app-sider" theme={themeMode === 'dark' ? 'dark' : 'light'}>
        <div className="app-brand">
          <Link to="/" className="app-brand__link">
            anomaly<span className="app-brand__dot">·</span>lab
          </Link>
        </div>
        <Menu
          theme={themeMode === 'dark' ? 'dark' : 'light'}
          mode="inline"
          selectedKeys={selectedKey ? [selectedKey] : []}
          items={NAV_ITEMS.map((item) => ({
            key: item.key,
            label: <Link to={item.key}>{item.label}</Link>,
          }))}
        />
        <div className="app-sider__footer">
          <Button
            type="text"
            onClick={onToggleTheme}
            style={{ color: token.colorTextSecondary, width: '100%' }}
          >
            {themeMode === 'dark' ? '☀ 浅色主题' : '☾ 暗色主题'}
          </Button>
        </div>
      </Sider>
      <Layout>
        <Content className="app-content">{children}</Content>
      </Layout>
    </Layout>
  )
}
