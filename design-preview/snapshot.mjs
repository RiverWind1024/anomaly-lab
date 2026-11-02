#!/usr/bin/env node
/**
 * 从真实后端抓一次快照，生成 design-preview/data-*.js。
 *
 *   node design-preview/snapshot.mjs [http://127.0.0.1:8000]
 *
 * 样张里出现的每一个数字都来自这里，不手写。
 */
import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const OUT = dirname(fileURLToPath(import.meta.url))

async function get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(path + ' → ' + res.status)
  return res.json()
}

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(path + ' → ' + res.status)
  return res.json()
}

const stamp = (s) => s ? s.replace('.000000', '').replace('+00:00', 'Z') : ''

function js(file, name, value) {
  const body = JSON.stringify(value)
  writeFileSync(join(OUT, file), `window.SAMPLE = window.SAMPLE || {}\nwindow.SAMPLE.${name} = ${body}\n`)
  console.log('written', file, (body.length / 1024).toFixed(1) + ' KB')
}

/** 500 点按 2 抽 1（251 点），保留峰值所在位置，够画又不糊。 */
function thin(timestamps, values, scores) {
  const keep = []
  for (let i = 0; i < timestamps.length; i += 2) keep.push(i)
  if (keep[keep.length - 1] !== timestamps.length - 1) keep.push(timestamps.length - 1)
  return {
    timestamps: keep.map((i) => timestamps[i]),
    values: keep.map((i) => values[i]),
    scores: keep.map((i) => scores[i]),
  }
}

const [overview, catalog, alerts, storage, summary, series, runs1, runs2] = await Promise.all([
  get('/api/platform/overview'),
  get('/api/platform/catalog'),
  get('/api/platform/alerts'),
  get('/api/platform/storage'),
  get('/api/summary'),
  get('/api/series'),
  get('/api/platform/jobs/1/runs'),
  get('/api/platform/jobs/2/runs'),
])

// ── 两条序列的检测结果 ──
const previews = {}
for (const sid of ['demo-metric:web-api', 'demo-metric:web-worker']) {
  const p = await get('/api/platform/jobs/' + catalog.jobs.find((j) => j.name === 'test1').id + '/preview?series_id=' + encodeURIComponent(sid))
  const t = thin(p.timestamps, p.values, p.scores)
  const k = t.scores.indexOf(Math.max(...t.scores))
  previews[sid] = {
    series: p.series_id,
    run_id: p.run_id,
    detector: p.detector,
    score_type: p.score_type,
    metric_class: p.metric_class,
    n_alerts: p.n_alerts,
    n_p0: p.n_p0,
    alert_threshold: p.alert_threshold,
    critical_threshold: p.critical_threshold,
    timestamps: t.timestamps,
    scores: t.scores.map((v) => Math.round(v * 1000) / 1000),
    values: t.values.map((v) => Math.round(v * 1000) / 1000),
    peak_ts: t.timestamps[k],
    peak_score: Math.round(t.scores[k] * 100) / 100,
  }
}

// ── 告警事件：统一字段名 ──
const events = alerts.events.map((e) => ({
  level: e.level,
  level_index: e.level_index,
  series: e.series_id,
  group: e.group,
  job: e.job_name,
  metric: e.metric_name,
  start: e.start_ts,
  end: e.end_ts,
  points: e.n_points,
  score: e.max_score,
  detector: e.detector,
  score_type: e.score_type,
  run_id: e.run_id,
}))

const bySeries = {}
for (const e of events) {
  const s = (bySeries[e.series] = bySeries[e.series] || { alerts: 0, p0: 0, events: 0 })
  s.events += 1
  if (e.level_index >= 2) s.p0 += 1
}
// overview.top_series 给的是告警条数（未合并前）
for (const t of overview.alerts.top_series) {
  if (bySeries[t.series_id]) bySeries[t.series_id].alerts = t.count
}
// 峰值来自各自的 preview
for (const id of Object.keys(previews)) {
  if (bySeries[id]) {
    bySeries[id].peak_ts = previews[id].peak_ts
    bySeries[id].peak_score = previews[id].peak_score
    previews[id].events = bySeries[id].events
  }
}

// 任务：overview 给状态，catalog 给间隔与下次运行
const jobs = overview.jobs.map((j) => {
  const c = catalog.jobs.find((x) => x.id === j.id) || {}
  return {
    ...j,
    interval_seconds: c.interval_seconds,
    next_run_at: c.next_run_at,
    window_points: c.window_points,
    alert_threshold: c.alert_threshold,
    critical_threshold: c.critical_threshold,
    alert_rules: c.alert_rules,
    created_at: c.created_at,
  }
})

const lastRun = overview.jobs.map((j) => j.last_run).filter(Boolean)
  .sort((a, b) => (a.started_at < b.started_at ? 1 : -1))[0]

js('data-overview.js', 'overview', {
  snapshot: stamp(lastRun.started_at),
  scope: { source: catalog.sources[0].name, metric: catalog.metrics[0].name },
  counts: overview.counts,
  runs: overview.runs,
  feedback: overview.feedback,
  jobs,
  events,
  finding: {
    total: overview.alerts.total,
    p0: overview.alerts.by_level.find((l) => l.level === 'P0')?.count ?? 0,
    by_series: bySeries,
  },
  trails: previews,
  default_series: 'demo-metric:web-api',
  backtest: {
    overall: summary.summary.overall,
    by_class: summary.summary.by_metric_class,
    by_detector: summary.summary.by_detector,
  },
  storage,
})

js('data-alerts.js', 'alerts', {
  snapshot: stamp(lastRun.started_at),
  events,
  levels: alerts.levels,
  series: alerts.series,
  jobs: alerts.jobs,
  skipped: alerts.skipped,
  total: overview.alerts.total,
  by_level: overview.alerts.by_level,
})

js('data-jobs.js', 'jobs', {
  snapshot: stamp(lastRun.started_at),
  alerts_total: overview.alerts.total,
  jobs: catalog.jobs,
  metrics: catalog.metrics,
  sources: catalog.sources,
  overview_jobs: overview.jobs,
  runs: { 1: runs1.runs, 2: runs2.runs },
  storage,
  counts: overview.counts,
  runs_summary: overview.runs,
})

js('data-eval.js', 'evaluation', {
  snapshot: stamp(lastRun.started_at),
  alerts_total: overview.alerts.total,
  generated_at: summary.generated_at,
  title: summary.title,
  summary: summary.summary,
  rows: summary.rows,
  excluded: summary.excluded,
  series,
})

js('data-sources.js', 'sources', {
  snapshot: stamp(lastRun.started_at),
  alerts_total: overview.alerts.total,
  sources: catalog.sources,
  metrics: catalog.metrics,
  jobs: catalog.jobs,
  counts: overview.counts,
  // 数据浏览器：在数据源上只读地查几行，看看原始数据长什么样
  browse: await post('/api/platform/sources/' + catalog.sources[0].id + '/query', {
    sql: 'SELECT ts, series, value FROM metrics ORDER BY ts DESC LIMIT 8',
    limit: 8,
  }),
  trails: previews,
  series: Object.keys(previews).map((id) => ({
    id,
    group: id.split(':').pop(),
    detector: previews[id].detector,
    n_alerts: previews[id].n_alerts,
    n_p0: previews[id].n_p0,
    peak_score: previews[id].peak_score,
    peak_ts: previews[id].peak_ts,
  })),
})

// ── 检测记录 / 标注：每条序列都带上真实曲线与真值标记 ──
// 时间戳是等间隔的，只存起点与步长，页面再展开（120 × 500 个时间戳要 1.2 MB）
const details = {}
for (const s of series) {
  const values = await get('/api/series/' + encodeURIComponent(s.series_id) + '/values')
  const bad = await get('/api/badcases?series_id=' + encodeURIComponent(s.series_id))
  const ts = values.timestamps.map((t) => Date.parse(t + 'Z'))
  const step = ts.length > 1 ? (ts[ts.length - 1] - ts[0]) / (ts.length - 1) : 0
  const regular = ts.every((t, i) => i === 0 || t - ts[i - 1] === step)
  details[s.series_id] = {
    metric_class: s.metric_class,
    t0: values.timestamps[0],
    step_min: Math.round(step / 60000),
    regular,
    timestamps: regular ? null : values.timestamps,
    values: values.values.map((v) => Math.round(v * 1000) / 1000),
    labels: values.labels,
    threshold: bad.threshold,
    score_type: bad.score_type,
    detector: bad.detector,
    badcases: bad.badcases.map((b) => ({
      kind: b.kind,
      group: b.group,
      reason: b.reason,
      from: b.indices[0],
      to: b.indices[b.indices.length - 1],
    })),
  }
}

js('data-detections.js', 'detections', {
  snapshot: stamp(lastRun.started_at),
  alerts_total: overview.alerts.total,
  series,
  details,
  rows: summary.rows,
})

// 标注页复用同一批曲线，只多一份类型表与标注清单（当前为空）
js('data-annotate.js', 'annotate', {
  snapshot: stamp(lastRun.started_at),
  alerts_total: overview.alerts.total,
  types: [
    { value: 'spike', label: '尖峰' },
    { value: 'contextual', label: '上下文异常' },
    { value: 'drift', label: '漂移' },
    { value: 'freq_shift', label: '频率变化' },
    { value: 'variance_shift', label: '方差变化' },
    { value: 'flatline', label: '平线' },
  ],
  annotations: {},
})
