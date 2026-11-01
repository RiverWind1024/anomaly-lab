import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DataBrowser } from './DataBrowser'

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(
        JSON.stringify({
          columns: [
            { name: 'ts', type: 'TIMESTAMP' },
            { name: 'value', type: 'REAL' },
          ],
          rows: [['2026-10-30T09:00:00+00:00', 3.5]],
          total: 1,
          truncated: false,
          elapsed_ms: 7,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderBrowser(onUseAsMetric = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <DataBrowser sourceId={1} onUseAsMetric={onUseAsMetric} />
    </QueryClientProvider>,
  )
}

/**
 * 某一列的角色下拉。
 *
 * ⚠️ antd 的 Table 为了算列宽会多渲染一行「测量行」—— 表头被复制了一份；
 *    而且 `title` 会同时落在 Select 的根节点与选中项上。
 *    所以只在**真正的表头行**里找，并取第一个（Select 根节点）。
 */
async function columnRoleSelect(columnName: string) {
  const headerRow = (await screen.findAllByRole('row'))[0]
  const select = within(headerRow).getAllByTitle(`${columnName} 列的角色`)[0]
  return within(select).getByRole('combobox')
}

describe('DataBrowser', () => {
  it('显示编辑器与执行按钮', () => {
    renderBrowser()
    // ⚠️ 面板里有多个 textbox（SQL 编辑器 + RangePicker 的两个 + 时间列输入），
    //    用 placeholder 精确定位，别用 getByRole('textbox')
    expect(screen.getByPlaceholderText(/SELECT/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /执\s*行/ })).toBeTruthy()
  })

  it('执行后显示列名与行', async () => {
    const user = userEvent.setup()
    renderBrowser()
    await user.click(screen.getByRole('button', { name: /执\s*行/ }))
    // ⚠️ antd 的 Table 为了算列宽会多渲染一行「测量行」——
    //    同样的列名会出现两次，所以列名用 findAllByText。
    expect((await screen.findAllByText('ts')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('value')).length).toBeGreaterThan(0)
    expect(await screen.findByText('3.5')).toBeTruthy()
  })

  it('列头有角色下拉，能把某一列指派为时间列', async () => {
    const user = userEvent.setup()
    const onUseAsMetric = vi.fn()
    renderBrowser(onUseAsMetric)
    await user.click(screen.getByRole('button', { name: /执\s*行/ }))

    // 「value」列的角色下拉 → 选「时间列」
    await user.click(await columnRoleSelect('value'))
    await user.click(await screen.findByTitle('时间列'))

    await user.click(screen.getByRole('button', { name: '用这个结果建指标' }))
    expect(onUseAsMetric).toHaveBeenCalledTimes(1)
    const payload = onUseAsMetric.mock.calls[0][0]
    expect(payload.roles.time_column).toBe('value')
    // 角色只能属于一列 —— 原来的时间列让位
    expect(payload.roles.value_column).toBeUndefined()
  })

  it('自动推断：TIMESTAMP → 时间列、数值列 → 值列', async () => {
    const user = userEvent.setup()
    const onUseAsMetric = vi.fn()
    renderBrowser(onUseAsMetric)
    await user.click(screen.getByRole('button', { name: /执\s*行/ }))
    await user.click(await screen.findByRole('button', { name: '用这个结果建指标' }))

    const payload = onUseAsMetric.mock.calls[0][0]
    expect(payload.roles.time_column).toBe('ts')
    expect(payload.roles.value_column).toBe('value')
  })

  it('选「不使用」可以把某一列从角色里摘掉', async () => {
    const user = userEvent.setup()
    const onUseAsMetric = vi.fn()
    renderBrowser(onUseAsMetric)
    await user.click(screen.getByRole('button', { name: /执\s*行/ }))

    await user.click(await columnRoleSelect('ts'))
    await user.click(await screen.findByTitle('不使用'))

    await user.click(await screen.findByRole('button', { name: '用这个结果建指标' }))
    const payload = onUseAsMetric.mock.calls[0][0]
    expect(payload.roles.time_column).toBeUndefined()
    expect(payload.roles.value_column).toBe('value')
  })
})
