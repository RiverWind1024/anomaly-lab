import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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

function renderBrowser() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <DataBrowser sourceId={1} onUseAsMetric={vi.fn()} />
    </QueryClientProvider>,
  )
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
})
