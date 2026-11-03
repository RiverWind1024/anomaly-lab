import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, Descriptions, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { StateBoundary } from '../components/StateBoundary'
import { MetricForm, type MetricFormValues } from '../features/metrics/MetricForm'
import { DeleteButton } from '../features/delete/DeleteButton'
import {
  PREVIEW_STORAGE_KEY,
  readPreviewPayload,
} from '../features/metrics/previewBridge'
import { useCatalog } from '../features/jobs/queries'
import { useDeleteMetric } from '../features/delete/queries'
import type { CatalogJob, CatalogMetric, SourceQueryColumn } from '../api/types'

/**
 * 数据源详情页 —— **指标的父级**。
 *
 * 层级是 数据源 → 指标 → 序列：
 * 这里列的是「这个数据源下配了哪些指标」，点指标进指标详情。
 *
 * ⚠️ 这里**没有**「浏览数据」—— 数据浏览属于指标的编辑流程
 *    （新增/编辑指标时点「预览数据」开新页），放在这里是位置不对。
 */
export function SourceDetailPage() {
  const params = useParams<{ sourceId: string }>()
  const sourceId = Number(params.sourceId ?? 0)
  const catalog = useCatalog()
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<CatalogMetric | null>(null)
  /** 预览页带回来的取数配置 —— 用来给指标表单预填。 */
  const [browserResult, setBrowserResult] = useState<{
    sql: string
    columns: SourceQueryColumn[]
    time_column?: string
    value_column?: string
    group_column?: string
    time_format?: string
  } | null>(null)
  const deleteMetric = useDeleteMetric()

  /**
   * 接住预览页带回来的配置。
   *
   * ⚠️ 预览页开在新标签页里，用 localStorage 回传 ——
   *    storage 事件只在**别的**标签页触发，正好是这里要的。
   */
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== PREVIEW_STORAGE_KEY) return
      const payload = readPreviewPayload(event.newValue)
      // ⚠️ 消费掉 —— 别让同一份配置反复填表单
      window.localStorage.removeItem(PREVIEW_STORAGE_KEY)
      if (!payload) return
      setBrowserResult({
        sql: payload.sql,
        columns: payload.columns,
        time_column: payload.time_column,
        value_column: payload.value_column,
        group_column: payload.group_column,
        time_format: payload.time_format,
      })
      setEditing(null)
      setFormOpen(true)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const source = catalog.data?.sources.find((item) => item.id === sourceId)
  const metrics = (catalog.data?.metrics ?? []).filter((item) => item.source_id === sourceId)

  /**
   * 用这个源的指标跑着的检测任务。
   *
   * ⚠️ 层级链是 数据源 → 指标 → 任务 ——
   *    少了这一段，用户看不到「改这个源会影响谁」。
   */
  const metricIds = new Set(metrics.map((m) => m.id))
  const jobs = (catalog.data?.jobs ?? []).filter((job) => metricIds.has(job.metric_id))
  const metricNameById = new Map((catalog.data?.metrics ?? []).map((m) => [m.id, m.name]))

  const jobColumns: ColumnsType<CatalogJob> = [
    {
      title: '任务',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, row) => <Link to={`/jobs/${row.id}`}>{value}</Link>,
    },
    {
      title: '指标',
      dataIndex: 'metric_id',
      key: 'metric_id',
      width: 150,
      render: (value: number) => (
        <span className="mono dim">{metricNameById.get(value) ?? String(value)}</span>
      ),
    },
    {
      title: '算法',
      dataIndex: 'detector',
      key: 'detector',
      width: 110,
      render: (value: string) =>
        value === 'auto' ? (
          <span className="pill pill--auto">自动推荐</span>
        ) : (
          <span className="mono dim">{value}</span>
        ),
    },
    {
      title: '阈值',
      key: 'thresholds',
      width: 150,
      render: (_value, row) => (
        <span className="mono dim">
          {row.alert_threshold}×→P1 / {row.critical_threshold}×→P0
        </span>
      ),
    },
    {
      title: '间隔',
      dataIndex: 'interval_seconds',
      key: 'interval_seconds',
      width: 80,
      align: 'right',
      render: (value: number) => <span className="mono dim">{value}s</span>,
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 90,
      render: (value: boolean) => (
        <span className={`pill ${value ? 'pill--ok' : 'pill--p1'}`}>
          {value ? '启用' : '停用'}
        </span>
      ),
    },
  ]

  const columns: ColumnsType<CatalogMetric> = [
    {
      title: '指标',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, row) => <Link to={`/metrics/${row.id}`}>{value}</Link>,
    },
    {
      title: '分组列',
      dataIndex: 'group_column',
      key: 'group_column',
      width: 140,
      render: (value: string | null) =>
        value ? <span className="mono">{value}</span> : <span className="muted">—</span>,
    },
    {
      title: '频率',
      dataIndex: 'freq',
      key: 'freq',
      width: 100,
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '时间格式',
      dataIndex: 'time_format',
      key: 'time_format',
      width: 130,
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_value, row) => (
        <Space size="small">
          <Button
            size="small"
            onClick={() => {
              setEditing(row)
              setFormOpen(true)
            }}
          >
            编辑
          </Button>
          {/* ⚠️ 删除必须走 DeleteButton —— 它带**影响预览**与二次确认。 taste-skill-ignore
              裸按钮误点就没了，而删指标会连带删掉任务与运行记录。 */}
          <DeleteButton
            target="metric"
            id={row.id}
            name={row.name}
            catalog={catalog.data}
            loading={deleteMetric.isPending && deleteMetric.variables === row.id}
            onConfirm={() => deleteMetric.mutate(row.id)}
          />
        </Space>
      ),
    },
  ]

  /**
   * 指标表单的预填值。
   *
   * ⚠️ 必须 memo —— 不然每次父组件重渲染都是新对象，
   *    MetricForm 的同步 effect 会把用户正在敲的内容冲掉。
   */
  const metricInitialValues = useMemo<Partial<MetricFormValues> | undefined>(
    () =>
      browserResult
        ? {
            // ⚠️ 只有 SQL 里带 $timefilter 才预填 query ——
            //    指标要求恰好一个 $timefilter，预填非法 SQL 会让用户白填一遍
            ...(browserResult.sql.includes('$timefilter')
              ? { query: browserResult.sql }
              : {}),
            time_column: browserResult.time_column ?? '',
            value_column: browserResult.value_column ?? '',
            group_column: browserResult.group_column ?? '',
            time_format: browserResult.time_format ?? 'iso_utc',
          }
        : undefined,
    [browserResult],
  )

  if (catalog.data && !source) {
    return (
      <div className="page">
        <header className="page__header">
          <h1 className="page__title">数据源</h1>
        </header>
        <div className="empty-state">
          <p className="empty-state__title">数据源不存在或已被删除</p>
          <Link to="/sources">← 回到数据源列表</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="titlebar">
        <h1>{source?.name ?? '数据源'}</h1>
        <div className="titlebar__actions">
          <Link className="link" to="/sources">
            ← 数据源
          </Link>
          <Button type="primary" onClick={() => setFormOpen(true)}>
            新增指标
          </Button>
        </div>
      </header>

      <section className="panel" aria-labelledby="srcInfoTitle">
        <div className="panel__head">
          <div>
            <h2 className="panel__title" id="srcInfoTitle">
              数据源
            </h2>
            <p className="panel__meta mono">
              {metrics.length} 个指标 · {jobs.length} 个检测任务
            </p>
          </div>
        </div>
        <Descriptions size="small" column={3} bordered className="source-detail__info">
          <Descriptions.Item label="类型">
            <Tag>{source?.kind ?? '—'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="路径">
            <span className="mono">{source?.path ?? '—'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            <span className="mono">{source?.created_at?.slice(0, 19).replace('T', ' ') ?? '—'}</span>
          </Descriptions.Item>
        </Descriptions>
      </section>

      <StateBoundary
        isLoading={catalog.isPending}
        error={catalog.error}
        data={metrics}
        isEmpty={(data) => data.length === 0}
        emptyTitle="这个数据源还没有指标"
        emptyHint="指标定义「从哪个数据源、取哪些列、怎么算频率」—— 没有指标就没法建检测任务"
      >
        {(data) => (
          <section className="panel" aria-labelledby="srcMetricsTitle">
            <div className="panel__head">
              <div>
                <h2 className="panel__title" id="srcMetricsTitle">
                  指标
                </h2>
                <p className="panel__meta mono">共 {data.length} 个指标</p>
              </div>
            </div>
            <Table<CatalogMetric>
              rowKey="id"
              columns={columns}
              dataSource={data}
              size="middle"
              pagination={false}
              scroll={{ x: 'max-content' }}
            />
          </section>
        )}
      </StateBoundary>

      {jobs.length > 0 ? (
        <section className="panel" aria-labelledby="srcJobsTitle">
          <div className="panel__head">
            <div>
              <h2 className="panel__title" id="srcJobsTitle">
                检测任务
              </h2>
              <p className="panel__meta mono">
                用这个源的指标跑着的任务 · {jobs.length} 个
              </p>
            </div>
          </div>
          <Table<CatalogJob>
            rowKey="id"
            columns={jobColumns}
            dataSource={jobs}
            size="middle"
            pagination={false}
            scroll={{ x: 'max-content' }}
          />
        </section>
      ) : null}

      <MetricForm
        open={formOpen}
        sources={catalog.data?.sources ?? []}
        editing={editing}
        // ⚠️ 不给默认数据源的话，从浏览器建的指标「数据源」是空的
        defaultSourceId={sourceId}
        initialValues={metricInitialValues}
        onCancel={() => {
          setFormOpen(false)
          setEditing(null)
          // ⚠️ 清掉浏览结果 —— 否则下次打开还带着上次的预填
          setBrowserResult(null)
        }}
      />
    </div>
  )
}
