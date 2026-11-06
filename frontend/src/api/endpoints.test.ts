/**
 * 端点覆盖守卫：拦截 fetch，打印每个封装函数实际会请求的 URL。
 *
 * 用 vitest 跑（能直接 import TS）。后端端点清单从源码 grep 后写进
 * EXPECTED_PATHS，缺失即失败。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { getCatalog, getOverview, createSource, createMetric, createJob, toggleJob, runJob, testRunJob, getRuns, getPreview, getCompare, createFeedback, getFeedback, getSuggestion, applySuggestion, getAlerts, getDetectionRecords, deleteJob, deleteMetric, deleteSource, updateSource, updateMetric, querySource, getStorage, pruneData, inspectLab, runLab, saveLabExperiment, listLabExperiments, getLabExperiment, getLabJobDraft, getLabWindow, evaluateLab } from './platform'
import { getSeries, getSeriesValues, getSummary, getBadcases, getExclusions, excludeEvaluationRow, restoreEvaluationRow, getProductionEvaluation, getProductionSamples, getRunSeriesDetail } from './series'
import { getAnnotations, saveAnnotations } from './annotate'

/**
 * 后端全部 /api/* 端点（从 src/anomaly_lab/web/*.py grep 得到，{id} 归一）。
 *
 * `/api/health` **故意不封装** —— 它是给运维探针用的，前端不消费。
 * 若哪天前端要展示后端健康状态，再加进来。
 *
 * ⚠️ 这份清单是**手写**的，所以它只保证「列出来的前端都封装了」。
 *    反向保证（后端有、这里漏了）由后端的守卫负责：
 *    `tests/web/test_api_contract.py::test_frontend_covers_all_backend_endpoints`。
 *    两条合起来才是完整的双向覆盖。
 */
const EXPECTED_PATHS = [
  '/api/platform/catalog',
  '/api/platform/overview',
  '/api/platform/alerts',
  '/api/platform/detections',
  '/api/platform/sources',
  '/api/platform/sources/{id}',
  '/api/platform/sources/{id}/query',
  '/api/lab/inspect',
  '/api/lab/run',
  '/api/lab/evaluate',
  '/api/lab/window',
  '/api/lab/experiments',
  '/api/lab/experiments/{id}',
  '/api/lab/experiments/{id}/job-draft',
  '/api/platform/metrics',
  '/api/platform/metrics/{id}',
  '/api/platform/jobs',
  '/api/platform/jobs/{id}',
  '/api/platform/jobs/{id}/run',
  '/api/platform/jobs/{id}/test-run',
  '/api/platform/jobs/{id}/runs',
  '/api/platform/jobs/{id}/preview',
  '/api/platform/jobs/{id}/compare',
  '/api/platform/feedback',
  '/api/platform/jobs/{id}/feedback',
  '/api/platform/jobs/{id}/feedback/suggestion',
  '/api/platform/jobs/{id}/apply-suggestion',
  '/api/platform/storage',
  '/api/platform/prune',
  '/api/series',
  '/api/series/{id}/values',
  '/api/summary',
  '/api/badcases',
  '/api/evaluation/exclusions',
  '/api/evaluation/production',
  '/api/evaluation/production/samples',
  '/api/runs/{id}/series/{id}',
  '/api/evaluation/exclusions/{id}/{id}',
  '/api/annotate/{id}',
]

/**
 * 把 URL 归一：去 origin、去 query、把路径末段的**动态部分**换成 {id}。
 *
 * 注意：封装层已经把序列 ID 用 encodeURIComponent 编过了（`demo-metric:web-api`
 * → `demo-metric%3Aweb-api`），所以这里要按**位置**替换，而不是按模板变量名。
 */
function normalize(url: string): string {
  let path = url.replace(/^https?:\/\/[^/]+/, '')
  path = path.split('?')[0]
  // 已编码的动态段 → {id}
  path = path.replace(/%3A[^/]*/gi, '{id}')
  // 未编码的 ${...} 插值 → {id}
  path = path.replace(/\$\{[^}]*\}/g, '{id}')
  // 形如 /api/series/<something>/values 里的 <something>
  path = path.replace(/\/api\/series\/[^/]+\/values/, '/api/series/{id}/values')
  path = path.replace(/\/api\/annotate\/[^/]+$/, '/api/annotate/{id}')
  // 排除端点有两个动态段（序列 + 算法）
  path = path.replace(
    /\/api\/evaluation\/exclusions\/[^/]+\/[^/]+$/,
    '/api/evaluation/exclusions/{id}/{id}',
  )
  // 实验记录 id 不是数字（时间戳-随机串），单独归一
  path = path.replace(/\/api\/lab\/experiments\/[^/]+/, '/api/lab/experiments/{id}')
  // run 里的序列 id 含冒号（demo-metric:web-api），单独归一
  path = path.replace(
    /\/api\/runs\/\d+\/series\/[^/]+$/,
    '/api/runs/{id}/series/{id}',
  )
  // 纯数字的路径段（job id 等）→ {id}
  path = path.replace(/\/\d+(?=\/|$)/g, '/{id}')
  return path
}

let calls: string[] = []

beforeEach(() => {
  calls = []
  vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
    calls.push(normalize(String(input)))
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('端点封装层', () => {
  it('每个封装函数都打到后端真实存在的路径上', async () => {
    await getCatalog()
    await getOverview()
    await createSource({ name: 's', path: '/p' })
    await createMetric({ source_id: 1, name: 'm', query: 'q', time_column: 't', value_column: 'v' })
    await createJob({ metric_id: 1, name: 'j' })
    await toggleJob(7, { enabled: true })
    await runJob(7)
    await testRunJob(7)
    await getRuns(7)
    await getPreview(7)
    await getPreview(7, { runId: 3, seriesId: 'a:b' })
    await getCompare(7)
    await getCompare(7, { seriesId: 'a:b', detectors: ['iqr'] })
    await createFeedback({ job_id: 1, series_id: 's', start_ts: 't1', end_ts: 't2', kind: 'missed' })
    await getFeedback(7)
    await getSuggestion(7)
    await getSuggestion(7, 3)
    await applySuggestion(7, { multiplier: 2.5 })
    await getAlerts()
    await getAlerts({ jobId: 1, level: 'P0' })
    await deleteJob(7)
    await deleteMetric(1)
    await deleteSource(1)
    await getStorage()
    await pruneData()
    await updateSource(1, { name: 'x' })
    await updateMetric(1, { query: 'q' })
    await querySource(1, { sql: 'SELECT 1' })
    await inspectLab({ kind: 'metric', metric_id: 1, start: '2026-01-01', end: '2026-01-02' })
    await runLab({ kind: 'metric', metric_id: 1, start: '2026-01-01', end: '2026-01-02' })
    await saveLabExperiment({
      kind: 'metric',
      metric_id: 1,
      start: '2026-01-01',
      end: '2026-01-02',
      result: {} as never,
    })
    await listLabExperiments()
    await getLabExperiment('20261104-120000-abc123')
    await getLabJobDraft('20261104-120000-abc123')
    await getLabWindow({
      kind: 'metric',
      metric_id: 1,
      start: '2026-01-01',
      end: '2026-01-02',
      series_id: 'm:a',
      window_index: 0,
    })
    await evaluateLab({ kind: 'synthetic', start: '2026-01-01', end: '2026-01-02' })
    await getDetectionRecords({ limit: 20 })
    await getProductionEvaluation()
    await getProductionSamples(50)
    await getRunSeriesDetail(1, 'demo-metric:web-api')
    await getSeries()
    await getSeriesValues('a:b')
    await getSummary()
    await getBadcases('a:b')
    await getExclusions()
    await excludeEvaluationRow('a:b', 'iqr')
    await restoreEvaluationRow('a:b', 'iqr')
    await getAnnotations('a:b')
    await saveAnnotations('a:b', [
      { start: '2026-01-01T00:00:00', end: '2026-01-01T01:00:00', type: 'anomaly' },
    ])

    const seen = new Set(calls)
    console.log('\n实际请求路径：')
    for (const c of calls) console.log('  ' + c)

    const missing = EXPECTED_PATHS.filter((p) => !seen.has(p))
    expect(missing, `后端有但封装层没覆盖：${missing.join(', ')}`).toEqual([])
  })

  it('编辑走 PATCH —— 与删除同路径，方法不能搞错', async () => {
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? 'GET' })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    await updateSource(1, { name: 'x' })
    await updateMetric(2, { query: 'q' })
    expect(calls[0].method).toBe('PATCH')
    expect(calls[0].url).toContain('/api/platform/sources/1')
    expect(calls[1].method).toBe('PATCH')
    expect(calls[1].url).toContain('/api/platform/metrics/2')
  })

  it('序列 ID 含冒号时被正确编码', async () => {
    await getSeriesValues('demo-metric:web-api')
    await getBadcases('demo-metric:web-api')
    await getAnnotations('demo-metric:web-api')
    // 归一后应与 /api/series/{id}/values 等一致
    expect(calls).toContain('/api/series/{id}/values')
    expect(calls).toContain('/api/badcases')
    expect(calls).toContain('/api/annotate/{id}')
  })

  it('预览与对比把查询参数挂到 URL 上', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
      urls.push(String(input))
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    await getPreview(7, { runId: 3, seriesId: 'x' })
    await getCompare(7, { detectors: ['iqr', 'mad'] })
    expect(urls[0]).toContain('run_id=3')
    expect(urls[0]).toContain('series_id=x')
    expect(urls[1]).toContain('detectors=iqr%2Cmad')
  })
})
