import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getOverview, getAlerts } from '../api/platform'
import { getSummary } from '../api/series'
import { useCatalog, usePreview } from '../features/jobs/queries'
import { StateBoundary } from '../components/StateBoundary'
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

/**
 * 概览页：整个平台的运行状况。
 *
 * 这一屏回答一个问题：**现在哪里有异常？**
 * 所以最大的那块是**异常分数轨迹**（这个产品自己的签名元素），
 * 数字在下面一条 KPI 条里，不用卡片占位。
 */
export function DashboardPage() {
  const overview = useQuery({ queryKey: ['overview'], queryFn: getOverview })
  const summary = useQuery({ queryKey: ['summary'], queryFn: getSummary })
  const catalog = useCatalog()
  const alerts = useQuery({ queryKey: ['alerts'], queryFn: () => getAlerts() })

  // 轨迹用哪个任务：**最近一次成功且跑出了序列**的那个
  const trailJob = useMemo(() => {
    const jobs = overview.data?.jobs ?? []
    return jobs
      .filter((j) => j.last_run && j.last_run.status === 'success' && j.last_run.n_series > 0)
      .sort((a, b) =>
        (a.last_run?.started_at ?? '') < (b.last_run?.started_at ?? '') ? 1 : -1,
      )[0]
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

  return (
    <div className="page">
      <StateBoundary
        isLoading={overview.isPending}
        error={overview.error}
        data={overview.data}
        isEmpty={(data) => data.counts.sources === 0 && data.counts.jobs === 0}
        emptyTitle="平台还没有任何配置"
        emptyHint="先建一个数据源与指标，再创建检测任务"
      >
        {(data) => (
          <>
            <header className="titlebar">
              <h1>概览</h1>
              <div className="titlebar__actions">
                <Link className="btn btn--primary" to="/alerts">
                  查看 P0 告警
                </Link>
              </div>
            </header>

              <ScoreTrail
              preview={preview.data}
              events={seriesEvents}
              series={seriesList}
              activeSeries={activeSeries}
              onSeriesChange={setPicked}
              isLoading={preview.isPending || preview.isFetching}
              error={preview.error}
            />

            <KpiStrip overview={data} summary={summary.data} />

            <div className="cols">
              <AlertEventsPanel
                events={seriesEvents}
                total={data.alerts.total}
                seriesId={activeSeries}
              />
              <JobHealthPanel
                jobs={data.jobs}
                catalogJobs={catalog.data?.jobs ?? []}
              />
            </div>

            <BacktestPanel summary={summary.data} />

            <RetentionPanel />
          </>
        )}
      </StateBoundary>
    </div>
  )
}
