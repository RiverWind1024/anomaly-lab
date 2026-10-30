import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceList } from './SourceList'
import { SourceForm } from './SourceForm'
import type { ReactElement } from 'react'
import type { Catalog, CatalogSource } from '../../api/types'

const SOURCE: CatalogSource = {
  id: 1,
  name: 'demo-sqlite',
  kind: 'sqlite',
  path: 'platform/source.db',
  created_at: '2026-10-30T00:00:00+00:00',
}

const CATALOG: Catalog = {
  sources: [SOURCE],
  metrics: [],
  jobs: [],
  detectors: [],
}

let calls: Array<{ url: string; method: string; body: string }> = []

/** 组件用了 react-query —— 必须包 QueryClientProvider。 */
function renderWithQuery(node: ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  // SourceList 里有 react-router 的 Link —— 必须包 Router
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
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

describe('数据源编辑', () => {
  it('列表有「编辑」按钮', () => {
    renderWithQuery(
      <SourceList
        isLoading={false}
        error={null}
        sources={[SOURCE]}
        catalog={CATALOG}
        onDelete={vi.fn()}
        deletingId={null}
        onEdit={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /编\s*辑/ })).toBeTruthy()
  })

  it('点「编辑」把这一行交给页面', () => {
    const onEdit = vi.fn()
    renderWithQuery(
      <SourceList
        isLoading={false}
        error={null}
        sources={[SOURCE]}
        catalog={CATALOG}
        onDelete={vi.fn()}
        deletingId={null}
        onEdit={onEdit}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /编\s*辑/ }))
    expect(onEdit).toHaveBeenCalledWith(SOURCE)
  })

  it('编辑弹窗带出原值，改完保存走 PATCH', async () => {
    renderWithQuery(
      <SourceForm
        open
        editing={SOURCE}
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    )
    // 原值已填入
    await waitFor(() => {
      expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('demo-sqlite')
    })
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '改名了' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch).toBeTruthy()
      expect(patch?.url).toContain('/api/platform/sources/1')
      expect(JSON.parse(patch?.body ?? '{}').name).toBe('改名了')
    })
  })

  it('编辑时不会误发 POST', async () => {
    renderWithQuery(<SourceForm open editing={SOURCE} onCancel={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => {
      expect(calls.some((c) => c.method === 'PATCH')).toBe(true)
    })
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })
})
