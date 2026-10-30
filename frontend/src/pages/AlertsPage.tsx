import { useState } from 'react'
import { AlertList } from '../features/alerts/AlertList'
import { useAlerts, type AlertFilters } from '../features/alerts/queries'

/** 告警中心：跨任务汇总的告警事件列表。 */
export function AlertsPage() {
  const [filters, setFilters] = useState<AlertFilters>({})
  const alerts = useAlerts(filters)

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">告警中心</h1>
        <p className="page__subtitle">
          {alerts.data
            ? `${alerts.data.events.length} 条告警事件（取各任务最近一次运行）`
            : '加载中…'}
        </p>
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
