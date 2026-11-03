import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { message } from 'antd'
import { MetricList } from '../features/metrics/MetricList'
import { useCatalog } from '../features/jobs/queries'
import { useDeleteMetric } from '../features/delete/queries'
import type { CatalogMetric } from '../api/types'

/**
 * 指标列表页 —— 「数据 › 指标」。
 *
 * ⚠️ **指标从数据源页搬到了这里** ——
 *    数据源页只管「有哪些数据源」，指标页管「有哪些指标」。
 *    两者是「数据」这个分组下的两个平级视图。
 *
 * ⚠️ 指标**从属**于数据源 —— 所以每行都显示它属于哪个源。
 */
export function MetricsPage() {
  const catalog = useCatalog()
  const navigate = useNavigate()
  const deleteMetric = useDeleteMetric()
  const [pendingEdit, setPendingEdit] = useState<CatalogMetric | null>(null)

  const handleDelete = (metricId: number) => {
    deleteMetric.mutate(metricId, {
      onSuccess: () => message.success('指标已删除'),
      onError: (err) =>
        message.error(err instanceof Error ? err.message : '删除失败'),
    })
  }

  /**
   * 编辑 → 跳到独立编辑页。
   *
   * ⚠️ 不用弹窗 —— 与「新增」同一条路径（`/metrics/:id/edit`），
   *    一套表单代码，新增与编辑不会走偏。
   */
  const handleEdit = (metric: CatalogMetric) => {
    setPendingEdit(metric)
    navigate(`/metrics/${metric.id}/edit`)
  }

  return (
    <div className="page">
      <header className="titlebar">
        <h1>指标</h1>
        <div className="titlebar__actions">
          <Link className="btn btn--primary" to="/metrics/new">
            新增指标
          </Link>
        </div>
      </header>

      <section className="panel" aria-labelledby="metricTitle">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="metricTitle">
              指标
            </h2>
            <p className="panel__meta mono">
              {catalog.data
                ? `${catalog.data.metrics.length} 个指标 · 取数方式与分组`
                : '加载中…'}
            </p>
          </div>
        </div>

        <MetricList
          isLoading={catalog.isPending}
          error={catalog.error}
          metrics={catalog.data?.metrics}
          sources={catalog.data?.sources}
          catalog={catalog.data}
          onDelete={handleDelete}
          deletingId={deleteMetric.isPending ? (deleteMetric.variables ?? null) : null}
          onEdit={handleEdit}
        />

        <div className="tfoot">
          <span>
            共 <b>{catalog.data?.metrics.length ?? 0}</b> 个指标
          </span>
          <span>
            <b>{catalog.data?.sources.length ?? 0}</b> 个数据源
          </span>
        </div>
      </section>

      {/* 跳转后立刻清掉 —— 免得再点一次「编辑」时状态是旧的 */}
      {pendingEdit ? <span className="muted" aria-hidden="true" /> : null}
    </div>
  )
}
