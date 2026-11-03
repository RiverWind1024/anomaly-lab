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
 * ⚠️ 取多少点 = **告警任务的「窗口点数」** ——
 *    指标本身没有「取多少数据」的设置（那是任务的配置），
 *    所以这里跟任务走，看到的就是任务真正会跑的那一段。
 */

/** 没有任何任务时用的默认窗口点数。 */
const DEFAULT_WINDOW_POINTS = 60

export function MetricChartPage() {
  const [params, setParams] = useSearchParams()
  const catalog = useCatalog()

  const sources = catalog.data?.sources ?? []
  const metrics = catalog.data?.metrics ?? []
  const jobs = catalog.data?.jobs ?? []

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
   * 窗口点数 —— 取该指标正在用的告警任务的设置。
   *
   * ⚠️ 指标本身**没有**「取多少数据」的字段 ——
   *    那是告警任务的配置（`window_points`）。
   *    这里跟任务走，看到的才是任务真正会取的那一段。
   */
  const metricJob = useMemo(
    () => jobs.find((item) => item.metric_id === metricId),
    [jobs, metricId],
  )
  const windowPoints = metricJob?.window_points ?? DEFAULT_WINDOW_POINTS

  const setParam = (key: string, value: number | undefined) => {
    const next = new URLSearchParams(params)
    if (value === undefined) {
      next.delete(key)
    } else {
      next.set(key, String(value))
    }
    setParams(next, { replace: true })
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
                ? `${metric.name} · ${metric.freq} · 窗口 ${windowPoints} 点`
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
              setParam('sourceId', next)
              setParam('metricId', undefined)
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
            onChange={(next) => setParam('metricId', next)}
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
            windowPoints={windowPoints}
            freq={metric.freq}
          />
          {/* ⚠️ 窗口在**告警任务**里设 —— 指标本身没有这个字段。 */}
          <p className="muted metric-chart-panel__note">
            这里取的是**最近 {windowPoints} 个点**（× {metric.freq}）——
            与告警任务的「窗口点数」一致。
            要改取多少数据，去
            {metricJob ? (
              <Link to={`/jobs/${metricJob.id}`}>告警任务</Link>
            ) : (
              '告警任务'
            )}
            里改「窗口点数」
            {metricJob ? '。' : '（这个指标还没有任务，先建一个）。'}
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
