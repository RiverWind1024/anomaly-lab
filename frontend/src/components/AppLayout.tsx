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
 *
 * ⚠️ 「告警」也是**分组**：「告警任务」（跑检测的定时任务）
 *    与「告警记录」（跨任务汇总的告警事件）——
 *    这两者是**产生与结果**的关系，同属一条告警链路。
 *
 * ⚠️ 名字相近但**不是一回事**，别混：
 *    - 「告警记录」(`/alerts`) = 有告警的事件，跨任务汇总；
 *    - 「检测记录」(`/detections`) = 每次运行里每条序列 × 算法的检测明细，
 *      没有告警的序列也在里面。
 *
 * ⚠️ 「评估与标注」是**第三个分组** —— 这三页是一个闭环：
 *    标注产真值 → 检测记录是预测 → 评估报告是两者对比。
 *    平铺着放，用户得自己脑补这个闭环。
 */
export const NAV_ITEMS: NavItem[] = [
  { key: '/', label: '概览' },
  {
    key: 'data',
    label: '数据',
    children: [
      { key: '/sources', label: '数据源' },
      { key: '/metrics', label: '指标' },
      { key: '/metrics/preview', label: '指标预览' },
      { key: '/lab', label: '指标预检' },
    ],
  },
  {
    key: 'alerting',
    label: '告警',
    children: [
      { key: '/jobs', label: '告警任务' },
      { key: '/alerts', label: '告警记录' },
    ],
  },
  {
    key: 'evaluation',
    label: '评估与标注',
    children: [
      { key: '/evaluation', label: '评估报告' },
      { key: '/annotate', label: '标注' },
      { key: '/detections', label: '检测记录' },
    ],
  },
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
 * 导航图标 —— 16px 线性图标，一笔画成，跟着文字的颜色走。
 *
 * ⚠️ 不用图标库：这里只有 9 个入口，手写路径比引依赖便宜，
 *    也避免每个图标各带一套自己的圆角与粗细。
 */
const NAV_ICON_PATHS: Record<string, ReactNode> = {
  // 概览：一条带峰值的轨迹
  '/': <path d="M1.8 9.8h2.6l1.6-4.4 2.2 7 1.8-3.2h4.2" />,
  // 数据：分层
  data: (
    <>
      <path d="M8 2.2 14 5 8 7.8 2 5 8 2.2Z" />
      <path d="M2 8.2 8 11l6-2.8M2 11.2 8 14l6-2.8" />
    </>
  ),
  // 数据源：机架
  '/sources': (
    <>
      <rect x="2.2" y="2.6" width="11.6" height="4.4" rx="1" />
      <rect x="2.2" y="9" width="11.6" height="4.4" rx="1" />
      <path d="M4.6 4.8h.01M4.6 11.2h.01" />
    </>
  ),
  // 指标：滑杆
  '/metrics': (
    <>
      <path d="M2 4.6h3.2M8.4 4.6H14M2 11.4h5.6M10.8 11.4H14" />
      <circle cx="7" cy="4.6" r="1.4" />
      <circle cx="9.4" cy="11.4" r="1.4" />
    </>
  ),
  // 指标预览：表格
  '/metrics/preview': (
    <>
      <rect x="2.2" y="2.8" width="11.6" height="10.4" rx="1" />
      <path d="M2.2 6.2h11.6M6.4 6.2v7" />
    </>
  ),
  // 指标预检：烧瓶
  '/lab': (
    <>
      <path d="M6.2 2.2h3.6M7 2.2v3.2L3.4 12a1.4 1.4 0 0 0 1.2 2h6.8a1.4 1.4 0 0 0 1.2-2L9 5.4V2.2" />
      <path d="M5.2 9.4h5.6" />
    </>
  ),
  // 告警：铃
  alerting: (
    <>
      <path d="M8 2.2a3.8 3.8 0 0 0-3.8 3.8c0 2.8-1.1 3.8-1.1 3.8h9.8s-1.1-1-1.1-3.8A3.8 3.8 0 0 0 8 2.2Z" />
      <path d="M6.6 12.6a1.5 1.5 0 0 0 2.8 0" />
    </>
  ),
  // 告警任务：循环时钟
  '/jobs': (
    <>
      <circle cx="8" cy="8" r="5.8" />
      <path d="M8 4.8V8l2.2 1.4" />
    </>
  ),
  // 告警记录：警示三角
  '/alerts': (
    <>
      <path d="M8 2.2 14 13H2L8 2.2Z" />
      <path d="M8 6.2v3.2M8 11.4h.01" />
    </>
  ),
  // 评估报告：柱状图
  '/evaluation': (
    <>
      <path d="M2.2 2v12h11.6" />
      <path d="M5.2 11.2V8M8 11.2V5.4M10.8 11.2V7" />
    </>
  ),
  // 检测记录：放大镜
  '/detections': (
    <>
      <circle cx="7.2" cy="7.2" r="4.6" />
      <path d="M10.6 10.6 14 14" />
    </>
  ),
  // 标注：笔
  '/annotate': (
    <>
      <path d="M3 13l.6-3 7-7a1.4 1.4 0 0 1 2 2l-7 6.9L3 13Z" />
      <path d="M9.4 4.2 11.8 6.6" />
    </>
  ),
}

function NavIcon({ name }: { name: string }) {
  return (
    <span className="app-nav__icon" aria-hidden="true">
      <svg
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {NAV_ICON_PATHS[name] ?? null}
      </svg>
    </span>
  )
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
  // 告警数挂在「告警记录」上 —— 它是一个待处理的队列，名词要说清楚
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
        icon: <NavIcon name={item.key} />,
        children: item.children.map((child) => ({
          key: child.key,
          icon: <NavIcon name={child.key} />,
          label: (
            <Link to={child.key} onClick={onNavigate}>
              {child.label}
              {/* ⚠️ 告警数挂在「告警记录」上 —— 它是一个待处理的队列，
                  名词要说清楚。
                  ⚠️ 这段徽标逻辑必须留在**子项**里 ——
                  「告警记录」现在是「告警」分组的子项，
                  走的是这条分支（原来的 leaf 分支已经够不到它了）。 */}
              {child.key === '/alerts' && alertCount > 0 ? (
                <span className="app-nav__count mono">{alertCount}</span>
              ) : null}
            </Link>
          ),
        })),
      }
    }
    return {
      key: item.key,
      icon: <NavIcon name={item.key} />,
      label: (
        <Link to={item.key} onClick={onNavigate}>
          {item.label}
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

/** 距上次运行多久 —— 侧栏页脚只报一个相对时间。 */
function sinceLabel(iso: string | null | undefined): string {
  if (!iso) return '还没有运行'
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return '—'
  const minutes = Math.round((Date.now() - then) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.round(hours / 24)} 天前`
}

/**
 * 侧栏页脚 —— 这个工作区现在是什么状态。
 *
 * ⚠️ 只报**真实**的运行状态（最近一次运行的相对时间 + 成败），
 *    不放版本号、版权这类占位信息。
 */
function WorkspaceFoot({
  themeMode,
  onToggleTheme,
}: {
  themeMode: ThemeMode
  onToggleTheme: () => void
}) {
  const overview = useQuery({ queryKey: ['overview'], queryFn: getOverview })
  const lastRun = (overview.data?.jobs ?? [])
    .map((job) => job.last_run)
    .filter((run): run is NonNullable<typeof run> => run !== null)
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))[0]

  return (
    <div className="app-sider__footer">
      <dl className="app-scope">
        <div className="app-scope__row">
          <dt>工作区</dt>
          <dd>本地 · SQLite</dd>
        </div>
        <div className="app-scope__row">
          <dt>最近运行</dt>
          <dd>
            {lastRun ? (
              <>
                <span
                  className={`app-scope__dot app-scope__dot--${
                    lastRun.status === 'success' ? 'ok' : 'p0'
                  }`}
                  aria-hidden="true"
                />
                {sinceLabel(lastRun.started_at)}
              </>
            ) : (
              '还没有运行'
            )}
          </dd>
        </div>
      </dl>
      <ThemeToggle themeMode={themeMode} onToggle={onToggleTheme} />
    </div>
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
   * ⚠️ `/metric-preview`（指标取数浏览器）也归「指标」——
   *    它是指标编辑流程的一环。
   *    ⚠️ 注意是 `/metric-`（单数 + 连字符）而不是 `/metric` ——
   *    否则 `/metrics/preview`（指标预览页）也会被算成「指标」，
   *    它的菜单项就永远不会高亮。
   */
  const selectedKey = (() => {
    const path = location.pathname
    if (path === '/') return '/'
    if (path.startsWith('/metric-')) return '/metrics'
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
        <WorkspaceFoot themeMode={themeMode} onToggleTheme={onToggleTheme} />
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

        <Content className="app-content">
          <div className="app-sheet">{children}</div>
        </Content>
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
