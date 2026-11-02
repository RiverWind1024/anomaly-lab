import { useEffect, useState } from 'react'
import { Drawer, Layout, Menu } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { ThemeMode } from '../theme/useThemeMode'
import { getOverview } from '../api/platform'
import './AppLayout.css'

const { Sider, Content } = Layout

/**
 * 侧边栏导航项。路径与 router.tsx 的路由表一一对应。
 *
 * ⚠️ 只有一级入口 —— 「指标」是数据源的子级，不该平铺成同级页面。
 *    指标页的入口在数据源详情里（/sources/:id → 指标列表 → /metrics/:id）。
 */
export const NAV_ITEMS = [
  { key: '/', label: '概览' },
  { key: '/sources', label: '数据源' },
  { key: '/jobs', label: '检测任务' },
  { key: '/alerts', label: '告警中心' },
  { key: '/evaluation', label: '评估报告' },
  { key: '/detections', label: '检测记录' },
  { key: '/annotate', label: '标注' },
]

export interface AppLayoutProps {
  themeMode: ThemeMode
  onToggleTheme: () => void
  children: ReactNode
}

/**
 * 品牌标记 —— 从产品自己的东西画出来：
 * 一条异常分数曲线，中间那个尖出来的点就是被抓住的异常。
 *
 * ⚠️ 不是「黑方块 + 一个字母」 —— 那是模板。
 */
function BrandMark() {
  return (
    <svg className="app-brand__mark" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M2 17.5 6 17.5 8.6 9.5 11.4 14.5 14.2 6.5 17 12.5 22 12.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="17" cy="12.5" r="2.1" className="app-brand__spark" />
    </svg>
  )
}

/**
 * 导航。桌面侧栏与手机抽屉共用一份，避免两处菜单不同步。
 */
function NavMenu({
  selectedKey,
  onNavigate,
}: {
  selectedKey: string
  onNavigate?: () => void
}) {
  // 告警数挂在「告警中心」上 —— 它是一个待处理的队列，名词要说清楚
  const overview = useQuery({ queryKey: ['overview'], queryFn: getOverview })
  const alertCount = overview.data?.alerts.total ?? 0

  return (
    <Menu
      mode="inline"
      selectedKeys={selectedKey ? [selectedKey] : []}
      items={NAV_ITEMS.map((item) => ({
        key: item.key,
        label: (
          <Link to={item.key} onClick={onNavigate}>
            {item.label}
            {item.key === '/alerts' && alertCount > 0 ? (
              <span className="app-nav__count mono">{alertCount}</span>
            ) : null}
          </Link>
        ),
      }))}
    />
  )
}

/** 主题切换 —— 用文字说明当前主题，不用 ☀/☾ 这类符号字符。 */
function ThemeToggle({ themeMode, onToggle }: { themeMode: ThemeMode; onToggle: () => void }) {
  const dark = themeMode === 'dark'
  return (
    <button
      type="button"
      className="app-theme"
      onClick={onToggle}
      aria-pressed={dark}
      title={dark ? '当前是暗色主题，点击切到浅色' : '当前是浅色主题，点击切到暗色'}
    >
      <span className="app-theme__dot" aria-hidden="true" />
      {dark ? '暗色主题' : '浅色主题'}
    </button>
  )
}

export function AppLayout({ themeMode, onToggleTheme, children }: AppLayoutProps) {
  const location = useLocation()
  const [navOpen, setNavOpen] = useState(false)

  // 详情页 /jobs/3 的高亮要落在 /jobs 上；
  // 指标页 /metrics/3 的高亮要落在 /sources 上（指标是数据源的子级）
  const selectedKey =
    NAV_ITEMS.find((item) => item.key !== '/' && location.pathname.startsWith(item.key))?.key ??
    (location.pathname.startsWith('/metrics') ? '/sources' : '/')

  const pageLabel =
    NAV_ITEMS.find((item) => item.key === selectedKey)?.label ?? '概览'

  // 路由变了就把手机导航收起来
  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

  return (
    <Layout className="app-layout">
      {/* 侧栏跟随主题 —— AntD 的 Menu theme="dark" 是写死的，
          浅色主题下会变成「暗侧栏 + 亮内容」，不协调 */}
      <Sider width={232} className="app-sider" theme={themeMode === 'dark' ? 'dark' : 'light'}>
        <div className="app-brand">
          <Link to="/" className="app-brand__link">
            <BrandMark />
            <span className="app-brand__name">
              anomaly<span className="app-brand__dot">·</span>lab
            </span>
          </Link>
        </div>
        <NavMenu selectedKey={selectedKey} />
        <div className="app-sider__footer">
          <ThemeToggle themeMode={themeMode} onToggle={onToggleTheme} />
        </div>
      </Sider>

      <Layout>
        {/* 手机顶栏 —— 桌面端隐藏 */}
        <header className="app-topbar">
          <button
            type="button"
            className="app-topbar__menu"
            onClick={() => setNavOpen(true)}
            aria-expanded={navOpen}
            aria-label="打开导航"
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path
                d="M3 5h14M3 10h14M3 15h14"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <span className="app-topbar__brand">
            anomaly<span className="app-brand__dot">·</span>lab
          </span>
          <span className="app-topbar__page">{pageLabel}</span>
        </header>

        <Content className="app-content">{children}</Content>
      </Layout>

      {/* 手机导航抽屉 —— 桌面端不出现 */}
      <Drawer
        placement="left"
        width={264}
        open={navOpen}
        onClose={() => setNavOpen(false)}
        title={
          <span className="app-drawer__brand">
            anomaly<span className="app-brand__dot">·</span>lab
          </span>
        }
        styles={{ body: { padding: '8px 8px 16px' } }}
      >
        <NavMenu selectedKey={selectedKey} onNavigate={() => setNavOpen(false)} />
        <div className="app-drawer__foot">
          <ThemeToggle themeMode={themeMode} onToggle={onToggleTheme} />
        </div>
      </Drawer>
    </Layout>
  )
}
