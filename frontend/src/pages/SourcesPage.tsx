import { useState } from 'react'
import { message } from 'antd'
import { SourceCreateButton, SourceForm } from '../features/sources/SourceForm'
import { SourceList } from '../features/sources/SourceList'
import { useCatalog } from '../features/jobs/queries'
import { useDeleteSource } from '../features/delete/queries'

/** 数据源页。 */
export function SourcesPage() {
  const catalog = useCatalog()
  const [formOpen, setFormOpen] = useState(false)
  const deleteSource = useDeleteSource()

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
      />

      <SourceForm open={formOpen} onCancel={() => setFormOpen(false)} />
    </div>
  )
}
