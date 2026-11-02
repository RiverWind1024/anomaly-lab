import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DataBrowser } from './DataBrowser'

/** 假远端返回的浏览结果 —— 列名故意与表单默认值不一样。 */
const RESULT = {
  columns: [
    { name: 'ts', type: 'TIMESTAMP' },
    { name: 'value', type: 'REAL' },
  ],
  rows: [['2026-10-30T09:00:00+00:00', 3.5]],
  total: 1,
  truncated: false,
  elapsed_ms: 7,
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify(RESULT), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderBrowser(onUseAsMetric = vi.fn(), kind = 'sqlite') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <DataBrowser sourceId={1} kind={kind} onUseAsMetric={onUseAsMetric} />
    </QueryClientProvider>,
  )
}

/** 最近一次请求的 body（JSON）。 */
function lastRequestBody(): Record<string, unknown> {
  const calls = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls
  const init = calls[calls.length - 1][1] as RequestInit
  return JSON.parse(String(init.body))
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
    // ⚠️ 面板里有多个 textbox（SQL 编辑器 + RangePicker 的两个 + 时间列输入 + 源时区输入），
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

  it('请求里带上 time_format 与 source_timezone', async () => {
    /* ⚠️ 浏览与指标运行时用同一套 `$timefilter` 渲染（D11）——
       浏览不声明时间格式/源时区，epoch 源的预览 ≠ 跑出来的。 */
    const user = userEvent.setup()
    renderBrowser()
    await user.click(screen.getByRole('button', { name: /执\s*行/ }))

    const body = lastRequestBody()
    expect(body.time_format).toBe('iso_utc')
    expect(body.source_timezone).toBe('UTC')
  })

  it('时间格式与源时区可以改，改了跟着请求走', async () => {
    const user = userEvent.setup()
    renderBrowser()
    await user.click(screen.getByRole('button', { name: /执\s*行/ }))

    // ⚠️ antd 的 Select 不是原生 select —— 点开再选选项
    //    ⚠️ `title` 同时落在 Select 根节点与选中项上 —— 取第一个
    const formatSelect = screen.getAllByTitle('时间格式')[0]
    await user.click(within(formatSelect).getByRole('combobox'))
    await user.click(await screen.findByTitle('epoch_s'))

    const timezone = screen.getByPlaceholderText(/源时区/)
    await user.clear(timezone)
    await user.type(timezone, 'Asia/Shanghai')

    await user.click(screen.getByRole('button', { name: /执\s*行/ }))

    const body = lastRequestBody()
    expect(body.time_format).toBe('epoch_s')
    expect(body.source_timezone).toBe('Asia/Shanghai')
  })

  it('INTEGER 的时间列提示用 epoch 解释', async () => {
    /* ⚠️ INTEGER 列按 iso 解释会静默落到 1970 年 —— 不报错但结果是错的。 */
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            columns: [
              { name: 'ts', type: 'INTEGER' },
              { name: 'value', type: 'REAL' },
            ],
            rows: [[1793318400, 3.5]],
            total: 1,
            truncated: false,
            elapsed_ms: 7,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    const user = userEvent.setup()
    renderBrowser()
    await user.click(screen.getByRole('button', { name: /执\s*行/ }))
    await user.type(screen.getByPlaceholderText(/时间列/), 'ts')

    expect(await screen.findByText(/epoch_s \/ epoch_ms/)).toBeTruthy()
  })

  it('非 SQL 型源不渲染 SQL 编辑器（spec §6.4）', () => {
    renderBrowser(vi.fn(), 'kafka')
    expect(screen.queryByPlaceholderText(/SELECT/)).toBeNull()
    expect(screen.getByText(/暂不支持 SQL 浏览/)).toBeTruthy()
  })
})
