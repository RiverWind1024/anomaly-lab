import { Link } from 'react-router-dom'
import { Button, Card, Col, Row, Space, Statistic, Table, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { StateBoundary } from '../components/StateBoundary'
import { getOverview, getStorage, pruneData } from '../api/platform'
import { getSummary } from '../api/series'
import type { OverviewJob } from '../api/types'

/** 反馈类型的中文名。 */
const FEEDBACK_LABEL: Record<string, string> = {
  correct: '正确',
  false_alarm: '误报',
  missed: '漏报',
  other: '其他',
}

/** 运行时长。 */
export function fmtDuration(startedAt: string | null, finishedAt: string | null): string {
  if (!startedAt || !finishedAt) return '—'
  const start = Date.parse(startedAt)
  const end = Date.parse(finishedAt)
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

/** 距上次运行多久。 */
export function sinceLabel(iso: string | null): string {
  if (!iso) return '从未运行'
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return '—'
  const minutes = Math.round((Date.now() - then) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.round(hours / 24)} 天前`
}

function runStatusTag(status: string | undefined): React.ReactNode {
  if (!status) return <span className="muted">未运行</span>
  if (status === 'success') return <Tag color="success">成功</Tag>
  if (status === 'running') return <Tag color="processing">运行中</Tag>
  return <Tag color="error">失败</Tag>
}

/** 字节数 → 人类可读。 */
export function fmtBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

/** 概览页：整个平台的运行状况。 */
export function DashboardPage() {
  const overview = useQuery({ queryKey: ['overview'], queryFn: getOverview })
  const summary = useQuery({ queryKey: ['summary'], queryFn: getSummary })

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">概览</h1>
        <p className="page__subtitle">平台运行状况 · 数据源到告警的全貌</p>
      </header>

      <StateBoundary
        isLoading={overview.isPending}
        error={overview.error}
        data={overview.data}
        isEmpty={(data) => data.counts.sources === 0 && data.counts.jobs === 0}
        emptyTitle="平台还没有任何配置"
        emptyHint="先建一个数据源与指标，再创建检测任务"
      >
        {(data) => (
          <div className="dashboard">
            <Row gutter={[12, 12]}>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="数据源" value={data.counts.sources} />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="指标" value={data.counts.metrics} />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic
                    title="检测任务"
                    value={data.counts.jobs}
                    suffix={
                      <span className="muted dashboard__stat-suffix">
                        {data.counts.enabled_jobs} 启用
                      </span>
                    }
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic
                    title="当前告警"
                    value={data.alerts.total}
                    valueStyle={
                      data.alerts.total > 0 ? { color: 'var(--status-p1)' } : undefined
                    }
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  {/* ⚠️ 不是「累计运行」—— 保留策略会把超窗的清掉，
                      这个数字是**保留窗口内**的运行次数。叫「累计」就是撒谎。 */}
                  <Statistic
                    title="保留期运行"
                    value={data.runs.total}
                    suffix={
                      <span className="muted dashboard__stat-suffix">
                        {data.runs.failed > 0 ? `${data.runs.failed} 失败` : '全部成功'}
                      </span>
                    }
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card size="small">
                  <Statistic title="人工反馈" value={data.feedback.total} />
                </Card>
              </Col>
            </Row>

            <Row gutter={[12, 12]} align="stretch">
              <Col span={8}>
                <Card size="small" title="告警分布">
                  {data.alerts.by_level.length === 0 ? (
                    <p className="muted dashboard__empty">当前没有告警</p>
                  ) : (
                    <ul className="dashboard__bars">
                      {data.alerts.by_level.map((item) => {
                        const max = data.alerts.by_level[0].count || 1
                        return (
                          <li key={item.level}>
                            <span className="dashboard__bar-label mono">{item.level}</span>
                            <span className="dashboard__bar-track">
                              <span
                                className="dashboard__bar-fill"
                                style={{ width: `${(item.count / max) * 100}%` }}
                              />
                            </span>
                            <span className="dashboard__bar-value mono">{item.count}</span>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                  {data.alerts.skipped > 0 ? (
                    <p className="muted dashboard__note">
                      {data.alerts.skipped} 个任务未纳入统计（没跑过 / 失败 / 运行中）——
                      <Link to="/alerts">去告警中心看</Link>
                    </p>
                  ) : null}
                </Card>
              </Col>

              <Col span={8}>
                <Card size="small" title="告警最多的序列">
                  {data.alerts.top_series.length === 0 ? (
                    <p className="muted dashboard__empty">没有告警</p>
                  ) : (
                    <ul className="dashboard__list">
                      {data.alerts.top_series.slice(0, 6).map((item) => (
                        <li key={item.series_id}>
                          <span className="mono dashboard__list-key">{item.series_id}</span>
                          <span className="mono muted">{item.count}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </Col>

              <Col span={8}>
                <Card size="small" title="人工反馈">
                  {data.feedback.by_kind.length === 0 ? (
                    <p className="muted dashboard__empty">还没有人工反馈</p>
                  ) : (
                    <ul className="dashboard__list">
                      {data.feedback.by_kind.map((item) => (
                        <li key={item.kind}>
                          <span>{FEEDBACK_LABEL[item.kind] ?? item.kind}</span>
                          <span className="mono muted">{item.count}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </Col>
            </Row>

            <Card size="small" title="任务运行状况">
              <JobHealthTable jobs={data.jobs} />
            </Card>

            <Card size="small" title="回测总体">
              {summary.data?.summary?.overall ? (
                <Space size="large" wrap>
                  <span>
                    <span className="muted">Precision</span>
                    <span className="mono">
                      {summary.data.summary.overall.precision.toFixed(3)}
                    </span>
                  </span>
                  <span>
                    <span className="muted">Recall</span>
                    <span className="mono">
                      {summary.data.summary.overall.recall.toFixed(3)}
                    </span>
                  </span>
                  <span>
                    <span className="muted">F1</span>
                    <span className="mono">{summary.data.summary.overall.f1.toFixed(3)}</span>
                  </span>
                  <span>
                    <span className="muted">Range-F1</span>
                    <span className="mono">
                      {summary.data.summary.overall.range_f1.toFixed(3)}
                    </span>
                  </span>
                  <span className="muted">
                    {summary.data.summary.overall.n_series} 条序列 · 真值{' '}
                    {summary.data.summary.overall.n_truth} 点 · 预测{' '}
                    {summary.data.summary.overall.n_pred} 点
                  </span>
                  <Link to="/evaluation">看完整报告 →</Link>
                </Space>
              ) : (
                <p className="muted">还没有回测报告 —— 先运行 <code>make evaluate</code>。</p>
              )}
            </Card>

            <RetentionCard />
          </div>
        )}
      </StateBoundary>
    </div>
  )
}

/**
 * 数据保留卡片：占用、策略、上次清理。
 *
 * ⚠️ 「自动清理」如果完全不可见，用户没法判断它在不在工作 ——
 *    作品集演示时，「数据在自动滚动」本身就是个卖点。
 */
function RetentionCard() {
  const qc = useQueryClient()
  const storage = useQuery({ queryKey: ['storage'], queryFn: getStorage })
  const prune = useMutation({
    mutationFn: pruneData,
    onSuccess: () => {
      // 清理会改「保留期运行」的数 —— 两边都要刷新
      void qc.invalidateQueries({ queryKey: ['storage'] })
      void qc.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  return (
    <Card size="small" title="数据保留">
      <StateBoundary
        isLoading={storage.isPending}
        error={storage.error}
        data={storage.data}
      >
        {(data) => (
          <div className="retention">
            <Space size="large" wrap>
              <span>
                <span className="muted">运行记录</span>
                <span className="mono">{data.runs.kept}</span>
                <span className="muted">条</span>
                <span className="mono">{fmtBytes(data.runs.bytes)}</span>
              </span>
              <span>
                <span className="muted">保留策略</span>
                <span className="mono">最近 {data.policy.retention_days} 天</span>
              </span>
              <span>
                <span className="muted">上次清理</span>
                <span>{data.last_pruned_at ? sinceLabel(data.last_pruned_at) : '还没清过'}</span>
              </span>
            </Space>
            <Button
              size="small"
              loading={prune.isPending}
              onClick={() => prune.mutate()}
            >
              立即清理
            </Button>
          </div>
        )}
      </StateBoundary>
    </Card>
  )
}

/** 任务运行状况表。 */
function JobHealthTable({ jobs }: { jobs: OverviewJob[] }) {
  const columns: ColumnsType<OverviewJob> = [
    {
      title: '任务',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, row) => <Link to={`/jobs/${row.id}`}>{value}</Link>,
    },
    {
      title: '状态',
      key: 'status',
      width: 110,
      render: (_value, row) =>
        row.enabled ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '最近一次',
      key: 'last_status',
      width: 120,
      render: (_value, row) => runStatusTag(row.last_run?.status),
    },
    {
      title: '检测序列',
      key: 'n_series',
      width: 100,
      align: 'right',
      render: (_value, row) => <span className="mono">{row.last_run?.n_series ?? '—'}</span>,
    },
    {
      title: '告警',
      key: 'n_alerts',
      width: 90,
      align: 'right',
      render: (_value, row) => <span className="mono">{row.last_run?.n_alerts ?? '—'}</span>,
    },
    {
      title: '耗时',
      key: 'duration',
      width: 130,
      render: (_value, row) =>
        fmtDuration(row.last_run?.started_at ?? null, row.last_run?.finished_at ?? null),
    },
    {
      title: '距上次运行',
      key: 'since',
      width: 130,
      render: (_value, row) => (
        <Tooltip title={row.last_run?.started_at ?? ''}>
          <span className="muted">{sinceLabel(row.last_run?.started_at ?? null)}</span>
        </Tooltip>
      ),
    },
    {
      title: '错误',
      dataIndex: 'last_run',
      key: 'error',
      render: (_value, row) =>
        row.last_run?.error ? (
          <span className="muted">{row.last_run.error.slice(0, 60)}</span>
        ) : (
          <span className="muted">—</span>
        ),
    },
  ]

  return (
    <Table<OverviewJob>
      rowKey="id"
      columns={columns}
      dataSource={jobs}
      size="small"
      pagination={false}
      scroll={{ x: 'max-content' }}
    />
  )
}
