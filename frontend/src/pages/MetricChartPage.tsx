import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Select, Space } from 'antd'
import { useCatalog } from '../features/jobs/queries'
import { MetricChartPanel } from '../features/metrics/MetricChartPanel'

/**
 * 指标预览 —— 选一个数据源、一个指标，看它的时序图与明细。
 *
 * ⚠️ 与「数据浏览器」(`/metric-preview`) 的分工：
 *    - 浏览器：**写 SQL** 看任意结果（定指标之前）；
 *    - 这里：看**已保存的指标**长什么样（定完之后）。
 *
 * ⚠️ 预览固定取最近 30 天 —— 不再依赖告警任务的窗口配置。
 */

export function MetricChartPage() {
  const [params, setParams] = useSearchParams()
  const catalog = useCatalog()

  const sources = catalog.data?.sources ?? []
  const metrics = catalog.data?.metrics ?? []

  const sourceIdParam = params.get('sourceId')
  const metricIdParam = params.get('metricId')

  const metric = useMemo(
    () => metrics.find((item) => item.id === Number(metricIdParam)),
    [metrics, metricIdParam],
  )
  const metricId = metric?.id

  /**
   * 数据源 —— ⚠️ **指标能反推数据源**。
   *
   * 从指标列表点「预览」过来时，URL 里只有 `metricId` ——
   * 不反推的话源是空的，指标下拉就是空的。
   */
  const sourceId = sourceIdParam ? Number(sourceIdParam) : metric?.source_id

  /** 该数据源下的指标 —— 指标必须属于选中的源。 */
  const sourceMetrics = useMemo(
    () => metrics.filter((item) => item.source_id === sourceId),
    [metrics, sourceId],
  )

  /**
   * 改 URL 参数。
   *
   * ⚠️ **必须用函数式更新** —— 不能基于渲染时的 `params` 快照构造新值。
   *
   *    快照式写法在这里是个**静默失效**：
   *    「换源」要同时改两个键（设 sourceId、删 metricId），
   *    两次调用都基于**同一个旧快照** → 第二次构造出的 URL
   *    把第一次写的 sourceId 冲掉了 → URL 变成空 →
   *    数据源没选中 → 指标下拉被禁用 → 用户「选不了指标」。
   *
   *    改成一次调用传所有改动 + 函数式更新，就不会互相覆盖。
   */
  const setParams_ = (changes: Record<string, number | undefined>) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(changes)) {
          if (value === undefined) {
            next.delete(key)
          } else {
            next.set(key, String(value))
          }
        }
        return next
      },
      { replace: true },
    )
  }

  return (
    <div className="page">
      <header className="titlebar">
        <h1>指标预览</h1>
        <div className="titlebar__actions">
          <Link className="link" to="/metrics">
            ← 指标
          </Link>
        </div>
      </header>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">选一个指标</h2>
            <p className="panel__meta mono">
              {metric
                ? `${metric.name} · 最近 30 天`
                : '先选数据源，再选指标'}
            </p>
          </div>
        </div>

        <Space size="large" wrap style={{ display: 'flex' }}>
          <Select
            style={{ width: 240 }}
            placeholder="数据源"
            showSearch
            optionFilterProp="label"
            value={sourceId}
            options={sources.map((source) => ({
              value: source.id,
              label: `${source.name} · ${source.kind}`,
            }))}
            onChange={(next) => {
              // ⚠️ 换源 → 换指标（不同源的指标不能混）
              //    两个键**一次改完** —— 分两次改会互相覆盖（见 setParams_ 的说明）。
              setParams_({ sourceId: next, metricId: undefined })
            }}
          />
          <Select
            style={{ width: 280 }}
            placeholder="指标"
            showSearch
            optionFilterProp="label"
            disabled={!sourceId}
            value={metricId}
            options={sourceMetrics.map((item) => ({
              value: item.id,
              label: item.name,
            }))}
            onChange={(next) => setParams_({ metricId: next })}
          />
        </Space>
      </section>

      {metric && sourceId ? (
        <section className="panel">
          <div className="panel__head">
            <div>
              <h2 className="panel__title">时序图</h2>
              <p className="panel__meta mono">
                {metric.query}
              </p>
            </div>
          </div>
          <MetricChartPanel
            sourceId={sourceId}
            config={{
              query: metric.query,
              time_column: metric.time_column,
              value_column: metric.value_column,
              group_column: metric.group_column,
              time_format: metric.time_format,
              source_timezone: metric.source_timezone,
            }}
          />
          {/* ⚠️ 预览固定取最近 30 天 —— 任务窗口是任务自己的配置。 */}
          <p className="muted metric-chart-panel__note">
            这里取的是**最近 30 天**的数据。告警任务的「时间窗口」不影响预览；
            数据粒度由指标的 SQL 决定。
          </p>
        </section>
      ) : (
        <section className="panel">
          <div className="empty-state">
            <p className="empty-state__title">还没选指标</p>
            <p className="muted">选一个数据源，再选它下面的指标。</p>
          </div>
        </section>
      )}
    </div>
  )
}
