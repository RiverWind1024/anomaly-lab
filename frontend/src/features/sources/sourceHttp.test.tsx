import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceForm } from './SourceForm'
import type { ReactElement } from 'react'
import type { CatalogSource } from '../../api/types'

/**
 * HTTP 数据源的表单。
 *
 * ⚠️ 这里的断言全是为了守住三个坑：
 *    1. config 是「整体替换」—— 必须带全字段；
 *    2. 脱敏值（••••）必须原样回传；
 *    3. headers/body 是 JSON 文本 —— 解析失败要报错。
 */

/** 后端脱敏后的样子（真实响应就是这样）。 */
const HTTP_SOURCE: CatalogSource = {
  id: 7,
  name: 'ch-http',
  kind: 'http',
  path: '',
  created_at: '2026-10-30T00:00:00+00:00',
  config: {
    url: 'https://ch:8123/?query={sql}',
    method: 'POST',
    format: 'json',
    headers: { 'X-Token': '••••', Authorization: 'Bearer ••••' },
    body: { q: '{sql}' },
    rows_path: 'data.items',
  },
}

let calls: Array<{ url: string; method: string; body: string }> = []

function renderWithQuery(node: ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: init?.method ?? 'GET',
        body: String(init?.body ?? ''),
      })
      return new Response('{}', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('HTTP 数据源表单', () => {
  it('类型是下拉框，不是自由文本', () => {
    renderWithQuery(<SourceForm open onCancel={vi.fn()} />)
    expect(screen.getByRole('combobox')).toBeTruthy()
  })

  it('编辑 HTTP 源：带出原值，保存时提交完整 config', async () => {
    renderWithQuery(
      <SourceForm open editing={HTTP_SOURCE} onCancel={vi.fn()} onSuccess={vi.fn()} />,
    )

    // 预填：URL、方法、格式、行数组路径
    await waitFor(() => {
      expect((screen.getByLabelText('URL') as HTMLInputElement).value).toBe(
        'https://ch:8123/?query={sql}',
      )
    })
    expect((screen.getByLabelText(/行数组路径/) as HTMLInputElement).value).toBe('data.items')

    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch).toBeTruthy()
      const payload = JSON.parse(patch?.body ?? '{}')
      // ⚠️ config 是「整体替换」—— 少一个顶层键后端就删了它
      expect(payload.config).toEqual({
        url: 'https://ch:8123/?query={sql}',
        method: 'POST',
        format: 'json',
        headers: { 'X-Token': '••••', Authorization: 'Bearer ••••' },
        body: { q: '{sql}' },
        rows_path: 'data.items',
      })
      // http 源没有「路径」
      expect(payload.path).toBe('')
      expect(payload.kind).toBe('http')
    })
  })

  it('脱敏的 header 值原样回传 —— 后端靠它还原真值', async () => {
    renderWithQuery(
      <SourceForm open editing={HTTP_SOURCE} onCancel={vi.fn()} onSuccess={vi.fn()} />,
    )
    // 表单里显示的就是脱敏值
    const headers = screen.getByLabelText(/请求头/) as HTMLTextAreaElement
    await waitFor(() => {
      expect(headers.value).toContain('••••')
    })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      const headersSent = JSON.parse(patch?.body ?? '{}').config?.headers
      expect(headersSent['X-Token']).toBe('••••')
      expect(headersSent.Authorization).toBe('Bearer ••••')
    })
  })

  it('headers 不是合法 JSON 时报错，不发请求', async () => {
    renderWithQuery(
      <SourceForm open editing={HTTP_SOURCE} onCancel={vi.fn()} onSuccess={vi.fn()} />,
    )
    const headers = screen.getByLabelText(/请求头/) as HTMLTextAreaElement
    await waitFor(() => {
      expect(headers.value).toContain('••••')
    })
    fireEvent.change(headers, { target: { value: '{ 坏掉的 JSON' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    expect(await screen.findByText(/不是合法的 JSON/)).toBeTruthy()
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('新增 HTTP 源：默认 method=GET、format=json 也照样提交', async () => {
    const user = userEvent.setup()
    renderWithQuery(<SourceForm open onCancel={vi.fn()} onSuccess={vi.fn()} />)

    // 类型从「SQLite 文件」切到「HTTP SQL 网关」
    await user.click(screen.getByRole('combobox'))
    await user.click(await screen.findByTitle('HTTP SQL 网关'))

    fireEvent.change(screen.getByLabelText('名称'), { target: { value: 'ch' } })
    fireEvent.change(screen.getByLabelText('URL'), {
      target: { value: 'https://ch:8123/?query={sql}' },
    })
    fireEvent.click(screen.getByRole('button', { name: /新\s*增/ }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')
      expect(post).toBeTruthy()
      const payload = JSON.parse(post?.body ?? '{}')
      expect(payload.config).toEqual({
        url: 'https://ch:8123/?query={sql}',
        method: 'GET',
        format: 'json',
        headers: {},
        body: {},
        rows_path: '',
      })
      expect(payload.path).toBe('')
    })
  })

  it('SQLite 源不带 config（后端对它不做整体替换）', async () => {
    renderWithQuery(<SourceForm open onCancel={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: 'local' } })
    fireEvent.change(screen.getByLabelText('路径'), {
      target: { value: 'platform/source.db' },
    })
    fireEvent.click(screen.getByRole('button', { name: /新\s*增/ }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')
      expect(post).toBeTruthy()
      const payload = JSON.parse(post?.body ?? '{}')
      expect(payload.kind).toBe('sqlite')
      expect(payload.config).toEqual({})
      expect(payload.path).toBe('platform/source.db')
    })
  })
})
