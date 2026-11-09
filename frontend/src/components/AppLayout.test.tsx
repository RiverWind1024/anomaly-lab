/**
 * 侧边栏导航结构。
 *
 * ⚠️ 「数据」是**分组**，下面挂「数据源」与「指标」——
 *    这两层是从属关系，平铺成一级入口会丢掉它。
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { AppLayout, NAV_ITEMS, NAV_ROUTES } from './AppLayout'

function renderLayout(path = '/') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppLayout themeMode="dark" onToggleTheme={vi.fn()}>
          <div>内容</div>
        </AppLayout>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify({ alerts: { total: 0 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('导航结构', () => {
  it('「数据」是分组，带数据源、指标、指标预览与指标预检四个子项', () => {
    const data = NAV_ITEMS.find((item) => item.key === 'data')
    expect(data).toBeTruthy()
    expect(data?.children?.map((c) => c.key)).toEqual([
      '/sources',
      '/metrics',
      '/metrics/preview',
      '/lab',
    ])
  })

  it('分组项本身不是路由 —— 展平后只剩可路由的项', () => {
    const keys = NAV_ROUTES.map((item) => item.key)
    expect(keys).toContain('/sources')
    expect(keys).toContain('/metrics')
    expect(keys).not.toContain('data')
  })

  it('「数据」分组展开后能看到数据源与指标', async () => {
    const user = userEvent.setup()
    renderLayout('/')
    // ⚠️ 分组默认收起 —— 先展开它
    await user.click(screen.getByText('数据'))
    expect(screen.getByText('数据源')).toBeTruthy()
    expect(screen.getByText('指标')).toBeTruthy()
  })

  it('指标页的高亮落在「指标」上，不是「数据源」', () => {
    renderLayout('/metrics')
    const selected = document.querySelector('.ant-menu-item-selected')
    expect(selected?.textContent).toContain('指标')
  })

  it('指标详情页的高亮也落在「指标」上', () => {
    renderLayout('/metrics/5')
    const selected = document.querySelector('.ant-menu-item-selected')
    expect(selected?.textContent).toContain('指标')
  })

  it('数据源详情页的高亮落在「数据源」上', () => {
    renderLayout('/sources/3')
    const selected = document.querySelector('.ant-menu-item-selected')
    expect(selected?.textContent).toContain('数据源')
  })

  it('指标预览页（/metric-preview）也算「指标」', () => {
    renderLayout('/metric-preview?sourceId=1')
    const selected = document.querySelector('.ant-menu-item-selected')
    expect(selected?.textContent).toContain('指标')
  })

  it('⚠️ 指标预览页（/metrics/preview）高亮在「指标预览」上，不是「指标」', () => {
    /* ⚠️ `/metrics/preview` 与 `/metric-preview` 只差一个 s ——
       选中态必须能分清，否则菜单项永远不会亮。 */
    renderLayout('/metrics/preview')
    const selected = document.querySelector('.ant-menu-item-selected')
    expect(selected?.textContent).toContain('指标预览')
  })
})

describe('「告警」分组', () => {
  it('是分组，带「告警任务」与「告警记录」两个子项', () => {
    const alerting = NAV_ITEMS.find((item) => item.key === 'alerting')
    expect(alerting).toBeTruthy()
    expect(alerting?.children?.map((c) => c.key)).toEqual(['/jobs', '/alerts'])
  })

  it('分组项本身不是路由 —— 展平后只剩可路由的项', () => {
    const keys = NAV_ROUTES.map((item) => item.key)
    expect(keys).toContain('/jobs')
    expect(keys).toContain('/alerts')
    expect(keys).not.toContain('alerting')
  })

  it('展开后能看到「告警任务」与「告警记录」', async () => {
    const user = userEvent.setup()
    renderLayout('/')
    await user.click(screen.getByText('告警'))
    expect(screen.getByText('告警任务')).toBeTruthy()
    expect(screen.getByText('告警记录')).toBeTruthy()
  })

  it('⚠️ 停在告警任务页时，「告警」分组自动展开', () => {
    /* ⚠️ 不自动展开的话，侧边栏只看到「告警」两个字被高亮，
       看不到是「告警任务」被选中 —— 用户会以为自己还在别的页。 */
    renderLayout('/jobs')
    const selected = document.querySelector('.ant-menu-item-selected')
    expect(selected?.textContent).toContain('告警任务')
  })

  it('⚠️ 停在告警记录页时，「告警」分组自动展开', () => {
    renderLayout('/alerts')
    const selected = document.querySelector('.ant-menu-item-selected')
    expect(selected?.textContent).toContain('告警记录')
  })

  it('「检测记录」是**独立的一级入口**，不是「告警」分组的子项', () => {
    /* ⚠️ 两个名字相近但不是一回事：
       告警记录 = 有告警的事件；检测记录 = 每条序列 × 算法的检测明细。 */
    const alerting = NAV_ITEMS.find((item) => item.key === 'alerting')
    expect(alerting?.children?.map((c) => c.key)).not.toContain('/detections')
    expect(NAV_ROUTES.map((item) => item.key)).toContain('/detections')
  })

  it('⚠️ 告警数徽标挂在「告警记录」上', async () => {
    /* 徽标代码在子项分支里 —— 改成子项后如果忘了挪，徽标就消失了。 */
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ alerts: { total: 7 } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const user = userEvent.setup()
    renderLayout('/')
    await user.click(screen.getByText('告警'))
    const badge = document.querySelector('.app-nav__count')
    expect(badge?.textContent).toBe('7')
  })
})

describe('「评估与标注」分组', () => {
  it('是分组，带评估报告、标注、检测记录、归档四个子项', () => {
    /* ⚠️ 这四页是一个闭环：标注产真值 → 检测记录是预测 → 评估报告是对比，
       归档是人工挑出来长期保留的那部分。 */
    const group = NAV_ITEMS.find((item) => item.key === 'evaluation')
    expect(group?.label).toBe('评估与标注')
    expect(group?.children?.map((c) => c.key)).toEqual([
      '/evaluation',
      '/annotate',
      '/detections',
      '/archives',
    ])
  })

  it('分组本身不是路由，四个子项仍是可路由的叶子', () => {
    const keys = NAV_ROUTES.map((item) => item.key)
    expect(keys).not.toContain('evaluation')
    for (const key of ['/evaluation', '/annotate', '/detections', '/archives']) {
      expect(keys).toContain(key)
    }
  })
})
