import { useMemo, useState } from 'react'
import { message } from 'antd'
import { SourceCreateButton, SourceForm } from '../features/sources/SourceForm'
import { SourceList } from '../features/sources/SourceList'
import { useCatalog } from '../features/jobs/queries'
import { useDeleteSource } from '../features/delete/queries'
import type { CatalogSource } from '../api/types'

/** 数据源页 —— 层级链的**第一级**。 */
export function SourcesPage() {
  const catalog = useCatalog()
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<CatalogSource | null>(null)
  const deleteSource = useDeleteSource()

  // 每个数据源下有几个指标 —— 列表里直接看得到，不用点进去
  const metricCounts = useMemo(() => {
    const counts = new Map<number, number>()
    for (const metric of catalog.data?.metrics ?? []) {
      counts.set(metric.source_id, (counts.get(metric.source_id) ?? 0) + 1)
    }
    return counts
  }, [catalog.data?.metrics])

  const handleDelete = (sourceId: number) => {
    deleteSource.mutate(sourceId, {
      onSuccess: () => message.success('数据源已删除'),
      onError: (err) =>
        message.error(err instanceof Error ? err.message : '删除失败'),
    })
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">数据源</h1>
        <p className="page__subtitle">
          {catalog.data ? `共 ${catalog.data.sources.length} 个数据源` : '加载中…'}
        </p>
      </header>

      <div className="page__toolbar">
        <SourceCreateButton onClick={() => setFormOpen(true)} />
      </div>

      <SourceList
        isLoading={catalog.isPending}
        error={catalog.error}
        sources={catalog.data?.sources}
        catalog={catalog.data}
        onDelete={handleDelete}
        deletingId={deleteSource.isPending ? (deleteSource.variables ?? null) : null}
        onEdit={(source) => {
          setEditing(source)
          setFormOpen(true)
        }}
        metricCounts={metricCounts}
      />

      <SourceForm
        open={formOpen}
        editing={editing}
        onCancel={() => {
          setFormOpen(false)
          setEditing(null)
        }}
      />
    </div>
  )
}
