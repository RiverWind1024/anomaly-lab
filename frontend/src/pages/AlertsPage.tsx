import { useState } from 'react'
import { AlertList } from '../features/alerts/AlertList'
import { useAlerts, type AlertFilters } from '../features/alerts/queries'

/** 告警中心：跨任务汇总的告警事件列表。 */
export function AlertsPage() {
  const [filters, setFilters] = useState<AlertFilters>({})
  const alerts = useAlerts(filters)

  return (
    <div className="page">
      <header className="titlebar">
        <h1>告警中心</h1>
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
