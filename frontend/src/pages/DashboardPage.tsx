import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getOverview, getAlerts } from '../api/platform'
import { getSummary } from '../api/series'
import { useCatalog, usePreview } from '../features/jobs/queries'
import { StateBoundary } from '../components/StateBoundary'
import { fmtUtcTime } from '../lib/format'
import { ScoreTrail } from '../features/overview/ScoreTrail'
import {
  AlertEventsPanel,
  BacktestPanel,
  JobHealthPanel,
  KpiStrip,
  RetentionPanel,
} from '../features/overview/panels'
// 这三个格式化函数原本就导出于本页 —— 保留导出，别的地方与测试都在用
export {
  fmtBytes,
  sinceLabel,
  fmtRunDuration as fmtDuration,
} from '../features/overview/panels'

/** 序列 ID 的短名：`demo-metric:web-api` → `web-api`。 */
function shortName(seriesId: string | undefined): string {
  if (!seriesId) return '—'
  const idx = seriesId.lastIndexOf(':')
  return idx >= 0 ? seriesId.slice(idx + 1) : seriesId
}

/**
 * 概览页：整个平台的运行状况。
 *
 * 这一屏回答一个问题：**现在哪里有异常？**
 * 顺序按阅读逻辑排：一句发现 → 规模数字 → 轨迹与事件 → 任务与回测 → 保留。
 */
export function DashboardPage() {
  const overview = useQuery({ queryKey: ['overview'], queryFn: getOverview })
  const summary = useQuery({ queryKey: ['summary'], queryFn: getSummary })
  const catalog = useCatalog()
  const alerts = useQuery({ queryKey: ['alerts'], queryFn: () => getAlerts() })

  // 轨迹用哪个任务：**告警最多**的那次成功运行，并列时取更近的。
  // 概览要回答「现在哪里有异常」，所以先看有告警的那条，而不是盲目取最新。
  const trailJob = useMemo(() => {
    const jobs = overview.data?.jobs ?? []
    return jobs
      .filter((j) => j.last_run && j.last_run.status === 'success' && j.last_run.n_series > 0)
      .sort((a, b) => {
        const byAlerts = (b.last_run?.n_alerts ?? 0) - (a.last_run?.n_alerts ?? 0)
        if (byAlerts !== 0) return byAlerts
        return (a.last_run?.started_at ?? '') < (b.last_run?.started_at ?? '') ? 1 : -1
      })[0]
  }, [overview.data?.jobs])

  const [picked, setPicked] = useState<string | undefined>(undefined)
  const preview = usePreview(trailJob?.id ?? 0, undefined, picked, trailJob != null)

  const seriesList = preview.data?.series ?? []
  const activeSeries = picked ?? preview.data?.series_id

  // 默认落在**告警最多**的那条序列上 —— 除非它正好就是后端给的第一条
  useEffect(() => {
    if (picked || seriesList.length === 0 || !preview.data) return
    const best = seriesList.slice().sort((a, b) => b.n_alerts - a.n_alerts)[0]
    if (best && best.series_id !== preview.data.series_id) setPicked(best.series_id)
  }, [preview.data, picked, seriesList])

  const seriesEvents = useMemo(
    () => (alerts.data?.events ?? []).filter((e) => e.series_id === activeSeries),
    [alerts.data?.events, activeSeries],
  )

  /** 当前序列的峰值 —— 发现句要说出「什么时候、多大」。 */
  const peak = useMemo(() => {
    const data = preview.data
    if (!data || data.series_id !== activeSeries) return null
    let best = -Infinity
    let idx = -1
    data.scores.forEach((score, i) => {
      if (score != null && score > best) {
        best = score
        idx = i
      }
    })
    if (idx < 0) return null
    return { score: best, ts: data.timestamps[idx] }
  }, [preview.data, activeSeries])

  return (
    <div className="page page--overview">
      <StateBoundary
        isLoading={overview.isPending}
        error={overview.error}
        data={overview.data}
        isEmpty={(data) => data.counts.sources === 0 && data.counts.jobs === 0}
        emptyTitle="平台还没有任何配置"
        emptyHint="先建一个数据源与指标，再创建告警任务"
      >
        {(data) => {
          const p0 = data.alerts.by_level.find((l) => l.level === 'P0')?.count ?? 0
          return (
            <>
              <header className="titlebar">
                <div className="titlebar__lead">
                  <h1>概览</h1>
                  {/* 一句发现：随选中序列与数据变化，不是写死的说明 */}
                  <p className="finding">
                    <span className="num">{data.alerts.total}</span> 条告警 ·{' '}
                    <span className="num">{p0}</span> 条 P0 —— 选中{' '}
                    <b>{shortName(activeSeries)}</b>
                    {peak ? (
                      <>
                        {' '}
                        在 <span className="num">{fmtUtcTime(peak.ts)}</span> 出现{' '}
                        <span className="num">{peak.score.toFixed(2)}σ</span> 峰值
                      </>
                    ) : null}
                    ，该序列 <span className="num">{seriesEvents.length}</span> 条告警
                  </p>
                </div>
                <div className="titlebar__actions">
                  <Link className="btn btn--primary" to="/alerts">
                    查看 P0 告警
                  </Link>
                </div>
              </header>

              <KpiStrip overview={data} summary={summary.data} />

              <div className="overview-primary">
                <ScoreTrail
                  preview={preview.data}
                  events={seriesEvents}
                  series={seriesList}
                  activeSeries={activeSeries}
                  onSeriesChange={setPicked}
                  isLoading={preview.isPending || preview.isFetching}
                  error={preview.error}
                />
                <AlertEventsPanel
                  events={seriesEvents}
                  total={data.alerts.total}
                  seriesId={activeSeries}
                />
              </div>

              <div className="overview-secondary">
                <JobHealthPanel
                  jobs={data.jobs}
                  catalogJobs={catalog.data?.jobs ?? []}
                />
                <BacktestPanel summary={summary.data} />
              </div>

              <RetentionPanel />
            </>
          )
        }}
      </StateBoundary>
    </div>
  )
}
