import { useState } from 'react'
import { Button, message } from 'antd'
import { MetricForm } from '../features/metrics/MetricForm'
import { MetricList } from '../features/metrics/MetricList'
import { useCatalog } from '../features/jobs/queries'
import { useDeleteMetric } from '../features/delete/queries'
import type { CatalogMetric } from '../api/types'

/** 指标页。 */
export function MetricsPage() {
  const catalog = useCatalog()
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<CatalogMetric | null>(null)
  const deleteMetric = useDeleteMetric()

  const sources = catalog.data?.sources ?? []

  const handleDelete = (metricId: number) => {
    deleteMetric.mutate(metricId, {
      onSuccess: () => message.success('指标已删除'),
      onError: (err) =>
        message.error(err instanceof Error ? err.message : '删除失败'),
    })
  }

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
        catalog={catalog.data}
        onDelete={handleDelete}
        deletingId={deleteMetric.isPending ? (deleteMetric.variables ?? null) : null}
        onEdit={(metric) => {
          setEditing(metric)
          setFormOpen(true)
        }}
      />

      <MetricForm
        open={formOpen}
        sources={sources}
        editing={editing}
        onCancel={() => {
          setFormOpen(false)
          setEditing(null)
        }}
      />
    </div>
  )
}
