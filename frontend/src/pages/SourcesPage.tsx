import { useMemo, useState } from 'react'
import { message } from 'antd'
import { SourceCreateButton, SourceForm } from '../features/sources/SourceForm'
import { SourceList } from '../features/sources/SourceList'
import { SourceMetrics } from '../features/sources/SourceMetrics'
import { SourceBrowse } from '../features/sources/SourceBrowse'
import { useCatalog } from '../features/jobs/queries'
import { useOverview } from '../features/overview/queries'
import { useDeleteSource } from '../features/delete/queries'
import type { CatalogSource } from '../api/types'

/** 数据源页 —— 层级链的**第一级**。 */
export function SourcesPage() {
  const catalog = useCatalog()
  const overview = useOverview()
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

  // 发现句 —— 这一屏在看什么
  const metric = catalog.data?.metrics?.[0]
  const topSeries = overview.data?.alerts.top_series ?? []
  const alertPoints = topSeries.reduce((a, s) => a + s.count, 0)

  return (
    <div className="page">
      <header className="titlebar">
        <div className="titlebar__lead">
          <h1>数据源</h1>
          <p className="finding">
            {catalog.data ? (
              <>
                共 <span className="mono">{catalog.data.sources.length}</span> 个数据源
                {metric ? (
                  <>
                    {' '}
                    —— <b>{metric.name}</b> 每 <span className="mono">{metric.freq}</span> 一个点，按{' '}
                    <b>{metric.group_column ?? '不分组'}</b> 分组，
                    <span className="mono">{topSeries.length}</span> 条序列、
                    <span className="mono">{alertPoints}</span> 个告警点
                  </>
                ) : null}
              </>
            ) : (
              '加载中…'
            )}
          </p>
        </div>
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

      {catalog.data && catalog.data.metrics.length > 0 ? (
        <section className="panel" aria-labelledby="metricTitle">
          <div className="panel__head">
            <div>
              <h2 className="panel__title" id="metricTitle">
                指标
              </h2>
              <p className="panel__meta mono">
                {catalog.data.metrics.length} 个指标 · 取数方式与分组
              </p>
            </div>
            <span className="link">在数据源详情里编辑</span>
          </div>

          <SourceMetrics
            metrics={catalog.data.metrics}
            sources={catalog.data.sources}
          />
        </section>
      ) : null}

      {catalog.data?.sources[0] && metric ? (
        <SourceBrowse source={catalog.data.sources[0]} metric={metric} />
      ) : null}

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
