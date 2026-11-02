import { useState } from 'react'
import { AlertList } from '../features/alerts/AlertList'
import { useAlerts, type AlertFilters } from '../features/alerts/queries'
import { useOverview } from '../features/overview/queries'

/** 告警中心：跨任务汇总的告警事件列表。 */
export function AlertsPage() {
  const [filters, setFilters] = useState<AlertFilters>({})
  const alerts = useAlerts(filters)
  const overview = useOverview()

  const events = alerts.data?.events ?? []
  const p0 = events.filter((e) => e.level_index >= 2).length
  const points = events.reduce((a, e) => a + e.n_points, 0)

  return (
    <div className="page">
      <header className="titlebar">
        <div className="titlebar__lead">
          <h1>告警中心</h1>
          <p className="finding">
            {alerts.data ? (
              <>
                <span className="mono">{events.length}</span> 条告警事件（取各任务最近一次运行） ·{' '}
                <span className="mono">{p0}</span> 条 P0 —— 覆盖{' '}
                <span className="mono">{points}</span> 个告警点
                {overview.data && overview.data.alerts.skipped > 0 ? (
                  <>
                    {' '}
                    · <span className="mono">{overview.data.alerts.skipped}</span> 个任务未纳入统计
                  </>
                ) : null}
              </>
            ) : (
              '加载中…'
            )}
          </p>
        </div>
      </header>

      <AlertList
        isLoading={alerts.isPending}
        error={alerts.error}
        data={alerts.data}
        filters={filters}
        onFiltersChange={setFilters}
      />
    </div>
  )
}
