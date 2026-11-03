import { useMemo, useState } from 'react'
import { message } from 'antd'
import { SourceCreateButton, SourceForm } from '../features/sources/SourceForm'
import { SourceList } from '../features/sources/SourceList'
import { useCatalog } from '../features/jobs/queries'
import { useDeleteSource } from '../features/delete/queries'
import type { CatalogSource } from '../api/types'

/**
 * 数据源页 —— 层级链的**第一级**。
 *
 * ⚠️ **这里不再展示指标列表** —— 指标搬到独立页面（「数据 › 指标」）。
 *    一个页面讲一件事；两个都塞进来，列表页就没人看得完了。
 *    数据源详情页里仍然能看到「这个源下有哪些指标」。
 */
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
      <header className="titlebar">
        <h1>数据源</h1>
        <div className="titlebar__actions">
          <SourceCreateButton onClick={() => setFormOpen(true)} />
        </div>
      </header>

      <section className="panel" aria-labelledby="srcTitle">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="srcTitle">
              数据源
            </h2>
            <p className="panel__meta mono">
              {catalog.data
                ? `${catalog.data.sources.length} 个数据源 · ${catalog.data.metrics.length} 个指标 · ${catalog.data.jobs.length} 个任务`
                : '加载中…'}
            </p>
          </div>
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

        <div className="tfoot">
          <span>
            共 <b>{catalog.data?.sources.length ?? 0}</b> 个数据源
          </span>
          <span>
            <b>{catalog.data?.metrics.length ?? 0}</b> 个指标
          </span>
          <span>
            <b>{catalog.data?.jobs.length ?? 0}</b> 个检测任务
          </span>
        </div>
      </section>

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
