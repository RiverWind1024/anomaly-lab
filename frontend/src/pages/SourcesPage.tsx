import { useState } from 'react'
import { SourceCreateButton, SourceForm } from '../features/sources/SourceForm'
import { SourceList } from '../features/sources/SourceList'
import { useCatalog } from '../features/jobs/queries'

/** 数据源页。 */
export function SourcesPage() {
  const catalog = useCatalog()
  const [formOpen, setFormOpen] = useState(false)

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
      />

      <SourceForm open={formOpen} onCancel={() => setFormOpen(false)} />
    </div>
  )
}
