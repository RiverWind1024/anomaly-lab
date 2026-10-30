import { useState } from 'react'
import { Button } from 'antd'
import { MetricForm } from '../features/metrics/MetricForm'
import { MetricList } from '../features/metrics/MetricList'
import { useCatalog } from '../features/jobs/queries'

/** 指标页。 */
export function MetricsPage() {
  const catalog = useCatalog()
  const [formOpen, setFormOpen] = useState(false)

  const sources = catalog.data?.sources ?? []

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">指标</h1>
        <p className="page__subtitle">
          {catalog.data ? `共 ${catalog.data.metrics.length} 个指标` : '加载中…'}
        </p>
      </header>

      <div className="page__toolbar">
        <Button type="primary" disabled={sources.length === 0} onClick={() => setFormOpen(true)}>
          新增指标
        </Button>
        {sources.length === 0 && (
          <span className="muted">先在「数据源」页新增一个数据源</span>
        )}
      </div>

      <MetricList
        isLoading={catalog.isPending}
        error={catalog.error}
        metrics={catalog.data?.metrics}
        sources={sources}
      />

      <MetricForm
        open={formOpen}
        sources={sources}
        onCancel={() => setFormOpen(false)}
      />
    </div>
  )
}
