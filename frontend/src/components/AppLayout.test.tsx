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
  it('「数据」是分组，带数据源与指标两个子项', () => {
    const data = NAV_ITEMS.find((item) => item.key === 'data')
    expect(data).toBeTruthy()
    expect(data?.children?.map((c) => c.key)).toEqual(['/sources', '/metrics'])
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
})
