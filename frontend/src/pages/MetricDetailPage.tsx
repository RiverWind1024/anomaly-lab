import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Alert, Button, Form, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { StateBoundary } from '../components/StateBoundary'
import { MetricFormFields, buildMetricPayload, type MetricFormValues } from '../features/metrics/MetricFormFields'
import { useCatalog, usePreview } from '../features/jobs/queries'
import { updateMetric } from '../api/platform'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { CatalogJob, SeriesEntry } from '../api/types'

export interface MetricDetailPageProps {
  metricId: number
}

/**
 * 指标详情页 —— 层级链的最后一环：**数据源 → 指标 → 序列**。
 *
 * 这里回答三件事：
 *   1. 这个指标怎么配的（可直接改）
 *   2. 哪些检测任务在用它
 *   3. 这些任务最近一次运行跑出了哪些序列
 *
 * ⚠️ 序列来自「任务最近一次运行」—— 指标本身不产生序列，
 *    是检测任务跑出来的。所以第 3 块挂在任务下面。
 */
export function MetricDetailPage() {
  const params = useParams<{ metricId: string }>()
  const metricId = Number(params.metricId ?? 0)
  const catalog = useCatalog()
  const [form] = Form.useForm<MetricFormValues>()
  const qc = useQueryClient()
  const [saved, setSaved] = useState(false)

  const metric = catalog.data?.metrics.find((item) => item.id === metricId)
  const source = catalog.data?.sources.find((item) => item.id === metric?.source_id)
  const jobs = (catalog.data?.jobs ?? []).filter((item) => item.metric_id === metricId)

  useEffect(() => {
    if (metric) {
      form.setFieldsValue({
        source_id: metric.source_id,
        name: metric.name,
        query: metric.query,
        time_column: metric.time_column,
        value_column: metric.value_column,
        group_column: metric.group_column ?? '',
        time_format: metric.time_format,
        source_timezone: metric.source_timezone,
        missing_policy: metric.missing_policy,
        freq: metric.freq,
      })
    }
  }, [metric, form])

  const save = useMutation({
    mutationFn: (payload: Parameters<typeof updateMetric>[1]) => updateMetric(metricId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['catalog'] })
      setSaved(true)
    },
  })

  const handleSave = async () => {
    let values: MetricFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSaved(false)
    save.mutate(buildMetricPayload(values))
  }

  if (catalog.data && !metric) {
    return (
      <div className="page">
        <header className="page__header">
          <h1 className="page__title">指标</h1>
        </header>
        <div className="empty-state">
          <p className="empty-state__title">指标不存在或已被删除</p>
          <Link to="/sources">← 回到数据源</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">{metric?.name ?? '指标'}</h1>
        <p className="page__subtitle">
          <Link to="/sources">数据源</Link>
          {source ? (
            <>
              {' / '}
              <Link to={`/sources/${source.id}`}>{source.name}</Link>
            </>
          ) : null}
          {' / '}
          {metric?.name ?? metricId}
        </p>
      </header>

      <section className="metric-detail__config">
        <h2 className="section__title">指标配置</h2>
        {save.error instanceof Error && (
          <Alert type="error" showIcon message={save.error.message} style={{ marginBottom: 16 }} />
        )}
        {saved && !save.isPending ? (
          <Alert type="success" showIcon message="已保存" style={{ marginBottom: 16 }} />
        ) : null}
        <Form form={form} layout="vertical" requiredMark="optional" disabled={!metric}>
          <MetricFormFields sources={catalog.data?.sources ?? []} />
          <Button type="primary" loading={save.isPending} onClick={handleSave}>
            保存配置
          </Button>
        </Form>
      </section>

      <section className="metric-detail__jobs">
        <h2 className="section__title">用这个指标的检测任务</h2>
        {jobs.length === 0 ? (
          <p className="muted">
            还没有检测任务用这个指标 —— 建一个任务，指标才会被跑起来、产生序列。
          </p>
        ) : (
          <ul className="metric-detail__job-list">
            {jobs.map((job) => (
              <li key={job.id}>
                <JobSeriesBlock job={job} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

/** 一个任务 + 它最近一次运行跑出的序列。 */
function JobSeriesBlock({ job }: { job: CatalogJob }) {
  const preview = usePreview(job.id, undefined, undefined, true)

  const columns: ColumnsType<SeriesEntry> = [
    {
      title: '序列',
      dataIndex: 'series_id',
      key: 'series_id',
      render: (value: string) => (
        <Link to={`/jobs/${job.id}/detections?series_id=${encodeURIComponent(value)}`}>
          <span className="mono">{value}</span>
        </Link>
      ),
    },
    {
      title: '分组',
      dataIndex: 'group',
      key: 'group',
      width: 160,
      render: (value: string | null) =>
        value ? <span className="mono">{value}</span> : <span className="muted">—</span>,
    },
    {
      title: '点数',
      dataIndex: 'n',
      key: 'n',
      width: 90,
      align: 'right',
    },
    {
      title: '告警点',
      dataIndex: 'n_alerts',
      key: 'n_alerts',
      width: 90,
      align: 'right',
    },
    {
      title: '形态',
      dataIndex: 'metric_class',
      key: 'metric_class',
      width: 140,
      render: (value: string | null) =>
        value ? <span className="mono">{value}</span> : <span className="muted">—</span>,
    },
  ]

  return (
    <div className="metric-detail__job">
      <div className="metric-detail__job-head">
        <Space size="small" wrap>
          <Link to={`/jobs/${job.id}`}>{job.name}</Link>
          <Tag color={job.enabled ? 'success' : 'default'}>{job.enabled ? '启用' : '停用'}</Tag>
          <span className="muted mono">{job.detector}</span>
        </Space>
      </div>

      <StateBoundary
        isLoading={preview.isPending}
        error={preview.error}
        data={preview.data}
        bizTitles={{ no_run: '这个任务还没有运行记录', no_series: '这次运行没有序列结果' }}
        emptyTitle="还没有跑出序列"
        emptyHint="运行一次任务后，这里会列出它检测到的序列"
      >
        {(data) => (
          <Table<SeriesEntry>
            rowKey="series_id"
            columns={columns}
            dataSource={data.series}
            size="small"
            pagination={false}
            scroll={{ x: 'max-content' }}
          />
        )}
      </StateBoundary>
    </div>
  )
}
