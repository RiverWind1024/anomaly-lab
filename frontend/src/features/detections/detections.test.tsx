import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Badcases, EvaluationRow, Summary } from '../../api/types'
import { DetectionsPage } from './DetectionsPage'
import { detectorLabel } from '../../lib/detectorLabels'

/**
 * 图表换成占位 —— ECharts 要 canvas，jsdom 没实现。
 *
 * ⚠️ 这不是「测不到就不测」—— 图表本身有独立的测试
 *    （`detectionChart.test.ts`）；这里要测的是**列表与详情的接线**。
 */
vi.mock('./DetectionChart', () => ({
  DetectionChart: () => <div data-testid="detection-chart" />,
}))

/** 造一条回测记录。 */
function row(seriesId: string, detector: string, extra: Partial<EvaluationRow> = {}): EvaluationRow {
  return {
    series_id: seriesId,
    detector,
    metric_class: 'periodic',
    score_type: 'zscore',
    threshold: 2.5,
    precision: 1,
    recall: 0.5,
    f1: 0.667,
    range_f1: 0.5,
    n_truth: 2,
    n_pred: 1,
    elapsed_ms: 0.1,
    ...extra,
  }
}

/** 25 条记录 → 每页 20 条 = 2 页。 */
const rows: EvaluationRow[] = [
  row('alpha', 'iqr'),
  row('alpha', 'mad'),
  ...Array.from({ length: 23 }, (_, i) => row(`series-${i}`, 'iqr')),
]

const summary: Summary = {
  generated_at: '2026-11-02T00:00:00+00:00',
  title: '回测',
  summary: {},
  rows,
}

const badcases: Badcases = {
  series_id: 'alpha',
  detector: 'iqr',
  threshold: 2.5,
  score_type: 'zscore',
  timestamps: ['2026-11-02T00:00:00'],
  values: [1],
  scores: [0.1],
  baseline: null,
  lower: null,
  upper: null,
  band_kind: null,
  badcases: [],
}

/** 把当前 URL 的 search 写进 DOM —— 断言 URL 变化用。 */
function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.search}</div>
}

function jsonResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => body,
    headers: { get: () => null },
  } as unknown as Response
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/summary')) return jsonResponse(summary)
    if (url.startsWith('/api/badcases')) return jsonResponse(badcases)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderPage(initialEntry = '/detections') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DetectionsPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** 左栏列表里的序列 ID（**只取列表** —— 详情头里也有序列名）。 */
function listIds(): string[] {
  return [...document.querySelectorAll('.detections-list__id')].map((el) => el.textContent ?? '')
}

/** 当前高亮的记录。 */
function activeIds(): string[] {
  return [...document.querySelectorAll('.detections-list__item.is-active .detections-list__id')].map(
    (el) => el.textContent ?? '',
  )
}

describe('DetectionsPage', () => {
  it('渲染筛选栏与记录列表', async () => {
    renderPage()
    await waitFor(() => expect(listIds().length).toBeGreaterThan(0))
    expect(screen.getByText('全部算法')).toBeTruthy()
    expect(screen.getByText('全部形态')).toBeTruthy()
    expect(screen.getByText('全部来源')).toBeTruthy()
  })

  it('列表项带算法标签（同序列不同算法分得清）', async () => {
    renderPage()
    await waitFor(() => expect(listIds().length).toBeGreaterThan(0))
    // alpha 出现两次（iqr 与 mad），两个算法标签都要在
    const tags = [...document.querySelectorAll('.detections-list__detector')].map(
      (el) => el.textContent,
    )
    // ⚠️ 列表显示**中文标签**（算法名是内部标识，不直接给人看）
    expect(tags).toContain(detectorLabel('iqr'))
    expect(tags).toContain(detectorLabel('mad'))
  })

  it('⚠️ 同序列的不同算法不会同时高亮', async () => {  // taste-skill-ignore
    renderPage('/detections?series_id=alpha&detector=mad')
    await waitFor(() => expect(listIds().length).toBeGreaterThan(0))
    await waitFor(() => expect(activeIds()).toEqual(['alpha']))
    // 只有一个高亮 —— 不是两个 alpha 都亮
    expect(document.querySelectorAll('.detections-list__item.is-active').length).toBe(1)
  })

  it('点列表项 → URL 带上 series_id 与 detector', async () => {
    renderPage()
    await waitFor(() => expect(listIds().length).toBeGreaterThan(0))

    const items = [...document.querySelectorAll('.detections-list__item')]
    // 第二项是 alpha/mad
    await userEvent.click(items[1])

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('series_id=alpha')
    })
    expect(screen.getByTestId('location').textContent).toContain('detector=mad')
  })

  it('⚠️ 深链接到后面的记录 → 自动拨到它所在的那页并高亮', async () => {  // taste-skill-ignore
    // series-19 是第 21 条（0 基 20）→ 在第 2 页
    renderPage('/detections?series_id=series-19&detector=iqr')
    await waitFor(() => expect(screen.getByText('series-19')).toBeTruthy())
    await waitFor(() => expect(activeIds()).toEqual(['series-19']))
  })

  it('筛选后计数正确', async () => {
    renderPage()
    await waitFor(() => expect(listIds().length).toBeGreaterThan(0))
    // 25 条全在 —— 计数在筛选栏右端
    const count = document.querySelector('.filter-bar__count')?.textContent ?? ''
    expect(count).toContain('25 条记录')
  })

  it('详情请求带上 detector', async () => {
    renderPage('/detections?series_id=alpha&detector=mad')
    await waitFor(() => expect(listIds().length).toBeGreaterThan(0))
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((call) => String(call[0]))
      expect(urls.some((url) => url.includes('detector=mad'))).toBe(true)
    })
  })
})
