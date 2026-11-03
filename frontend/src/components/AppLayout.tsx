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
 * 导航项。
 *
 * ⚠️ 分组项（「数据」）有 `children`，普通项没有 ——
 *    用显式类型而不是靠推断，`flatMap` 之后才不会变成
 *    「children 可能 undefined」的联合类型。
 */
interface NavItem {
  key: string
  label: string
  children?: NavLeaf[]
}

/** 可路由的导航项（没有子项）。 */
interface NavLeaf {
  key: string
  label: string
}

/**
 * 侧边栏导航项。路径与 router.tsx 的路由表一一对应。
 *
 * ⚠️ 「数据」是**分组**，下面挂「数据源」与「指标」——
 *    这两者是**从属关系**（指标从某个数据源取数），
 *    平铺成两个一级入口会丢掉这层关系。
 *    分组本身不是路由，选中的是它的子项。
 */
export const NAV_ITEMS: NavItem[] = [
  { key: '/', label: '概览' },
  {
    key: 'data',
    label: '数据',
    children: [
      { key: '/sources', label: '数据源' },
      { key: '/metrics', label: '指标' },
    ],
  },
  { key: '/jobs', label: '检测任务' },
  { key: '/alerts', label: '告警中心' },
  { key: '/evaluation', label: '评估报告' },
  { key: '/detections', label: '检测记录' },
  { key: '/annotate', label: '标注' },
]

/**
 * 所有**可路由**的导航项（展平分组）。
 *
 * ⚠️ 选中态与页面标题都从这里算 —— 分组项（「数据」）不是路由，
 *    混进来会让 `/data` 永远匹配不上。
 */
export const NAV_ROUTES: NavLeaf[] = NAV_ITEMS.flatMap((item) =>
  item.children ? item.children : [{ key: item.key, label: item.label }],
)

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

  /**
   * 展开的分组。
   *
   * ⚠️ **选中的子项所在的分组必须展开** ——
   *    否则停在「指标」页时，侧边栏只看到「数据」两个字被高亮，
   *    看不到是「指标」被选中 —— 用户会以为自己还在数据源页。
   *
   * ⚠️ 用受控的 `openKeys` 而不是 `defaultOpenKeys`：
   *    后者只在挂载时生效，路由切换后就不管用了。
   */
  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const group = NAV_ITEMS.find((item) =>
      item.children?.some((child) => child.key === selectedKey),
    )
    return group ? [group.key] : []
  })

  useEffect(() => {
    const group = NAV_ITEMS.find((item) =>
      item.children?.some((child) => child.key === selectedKey),
    )
    if (!group) return
    setOpenKeys((prev) => (prev.includes(group.key) ? prev : [...prev, group.key]))
  }, [selectedKey])

  /**
   * 导航项 → antd Menu 的 items。
   *
   * ⚠️ 分组项要挂 `children` —— antd 会自动渲染成可展开的子菜单。
   *    分组本身没有链接（它不是路由）。
   */
  const items = NAV_ITEMS.map((item) => {
    if (item.children) {
      return {
        key: item.key,
        label: item.label,
        children: item.children.map((child) => ({
          key: child.key,
          label: (
            <Link to={child.key} onClick={onNavigate}>
              {child.label}
            </Link>
          ),
        })),
      }
    }
    return {
      key: item.key,
      label: (
        <Link to={item.key} onClick={onNavigate}>
          {item.label}
          {item.key === '/alerts' && alertCount > 0 ? (
            <span className="app-nav__count mono">{alertCount}</span>
          ) : null}
        </Link>
      ),
    }
  })

  return (
    <Menu
      mode="inline"
      selectedKeys={selectedKey ? [selectedKey] : []}
      openKeys={openKeys}
      onOpenChange={(keys) => setOpenKeys(keys as string[])}
      items={items}
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

  /**
   * 当前选中的导航项。
   *
   * ⚠️ **最长前缀匹配** —— 详情页的高亮要落在列表页上：
   *    `/sources/3` → 数据源，`/metrics/5` → 指标。
   * ⚠️ `/metric-preview`（指标取数预览）也归「指标」——
   *    它是指标编辑流程的一环。
   */
  const selectedKey = (() => {
    const path = location.pathname
    if (path === '/') return '/'
    if (path.startsWith('/metric')) return '/metrics'
    const match = NAV_ROUTES.filter(
      (item) => item.key !== '/' && path.startsWith(item.key),
    ).sort((a, b) => b.key.length - a.key.length)[0]
    return match?.key ?? '/'
  })()

  const pageLabel = NAV_ROUTES.find((item) => item.key === selectedKey)?.label ?? '概览'

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
