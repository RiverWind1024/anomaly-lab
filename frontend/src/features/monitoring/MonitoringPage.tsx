import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ReactNode } from 'react'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtClock, fmtDateTimeSec } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import { useObservability } from './queries'
import { MonitoringChart } from './MonitoringChart'
import type {
  Observability,
  ObservabilityDetectorRow,
  ObservabilityJobRow,
  ObservabilityRouteRow,
  ObservabilityStageRow,
} from '../../api/types'
import { cssVar } from '../../theme/cssVar'
import './monitoring.css'

/** 阶段的中文名 —— 后端存的是 load / detect / persist。 */
const STAGE_LABELS: Record<string, string> = {
  load: '取数',
  detect: '检测',
  persist: '落盘',
}

/** SPA 兜底路由不是业务接口 —— 直接显示模板文本会让人以为接口叫这个名字。 */
const ROUTE_LABELS: Record<string, string> = {
  '/{full_path:path}': '前端页面（SPA 兜底）',
}

function fmtBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = Number(value)
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

function fmtDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total} 秒`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes} 分 ${total % 60} 秒`
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时 ${minutes % 60} 分`
}

function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function fmtMs(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value < 1) return '<1 ms'
  return `${Math.round(value)} ms`
}

/** 服务监控页：看这个服务自己活得怎么样。 */
export function MonitoringPage() {
  const query = useObservability(60)

  return (
    <div className="page monitoring">
      <header className="titlebar">
        <div className="titlebar__lead">
          <h1>服务监控</h1>
          <span className="dim">
            请求、任务、算法、调度器与资源的实时状态 —— 每{' '}
            {query.data?.interval_seconds ?? 60} 秒记一个点
          </span>
        </div>
        {query.data ? (
          <span className="monitoring__stamp mono dim">
            最近采样 {fmtDateTimeSec(query.data.service.snapshot_at)}（本地时间）
          </span>
        ) : null}
      </header>

      <StateBoundary
        isLoading={query.isPending}
        error={query.error}
        data={query.data}
        emptyTitle="还没有监控数据"
        emptyHint="服务刚启动时采样线程还没跑完第一轮，几秒后刷新"
      >
        {(data: Observability) => <MonitoringBody data={data} />}
      </StateBoundary>
    </div>
  )
}

function MonitoringBody({ data }: { data: Observability }) {
  const points = data.timeline
  const times = points.map((point) => fmtClock(point.at))
  const hasCurve = points.length >= 2
  const totalCalls = data.detectors.reduce((sum, row) => sum + row.calls, 0)
  const totalFallbacks = data.detectors.reduce((sum, row) => sum + row.fallbacks, 0)
  const totalRuns = data.jobs.reduce((sum, row) => sum + row.runs, 0)
  const totalAlerts = data.alerts.total

  return (
    <>
      <section className="kpis monitoring__kpis">
        <div className="kpi kpi--lead">
          <span className="kpi__k">服务</span>
          <span className="kpi__v">{fmtDuration(data.service.uptime_seconds)}</span>
          <span className="kpi__s mono">
            pid {data.service.pid} · {data.service.sampler_running ? '采样中' : '采样已停'}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi__k">调度器</span>
          <span className="kpi__v">
            {data.scheduler.alive ? '运行中' : '未运行'}
            {data.scheduler.alive ? null : (
              <Tag className="monitoring__tag" color="warning">
                停滞
              </Tag>
            )}
          </span>
          <span className="kpi__s">
            {fmtNum(data.scheduler.ticks)} 次 tick
            {data.scheduler.avg_tick_ms !== null
              ? ` · 平均 ${fmtMs(data.scheduler.avg_tick_ms)}`
              : ''}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi__k">接口请求</span>
          <span className="kpi__v mono">{fmtNum(data.http.total)}</span>
          <span className="kpi__s">
            错误 {fmtNum(data.http.errors)} · 进行中 {fmtNum(data.current.inflight)}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi__k">算法调用</span>
          <span className="kpi__v mono">{fmtNum(totalCalls)}</span>
          <span className="kpi__s">回退 {fmtNum(totalFallbacks)} 次</span>
        </div>
        <div className="kpi">
          <span className="kpi__k">检测运行</span>
          <span className="kpi__v mono">{fmtNum(totalRuns)}</span>
          <span className="kpi__s">
            告警区间 {fmtNum(totalAlerts)}
            {data.current.due_jobs ? ` · 待跑 ${data.current.due_jobs}` : ''}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi__k">存储</span>
          <span className="kpi__v mono">{fmtBytes(data.current.db_bytes)}</span>
          <span className="kpi__s">
            run 目录 {fmtBytes(data.current.runs_bytes)} · {fmtNum(data.current.runs_count)} 个文件
          </span>
        </div>
      </section>

      <div className="monitoring__grid">
        <ChartPanel
          title="流量与错误"
          hint="每分钟请求数；错误只统计 5xx"
          hasCurve={hasCurve}
          interval={data.interval_seconds}
        >
          <MonitoringChart
            times={times}
            showSymbol={points.length <= 8}
            leftUnit="次/分"
            series={[
              {
                name: '请求',
                data: points.map((point) => point.requests),
                color: cssVar('--accent-text', '#6da8e3'),
                area: true,
              },
              {
                name: '5xx',
                data: points.map((point) => point.errors),
                color: cssVar('--status-p0', '#ef4444'),
              },
            ]}
          />
        </ChartPanel>

        <ChartPanel
          title="接口延迟"
          hint="整体分位，不是单条路由；单位毫秒"
          hasCurve={hasCurve}
          interval={data.interval_seconds}
        >
          <MonitoringChart
            times={times}
            showSymbol={points.length <= 8}
            leftUnit="ms"
            series={[
              {
                name: 'P50',
                data: points.map((point) => point.p50_ms),
                color: cssVar('--accent-text', '#6da8e3'),
              },
              {
                name: 'P95',
                data: points.map((point) => point.p95_ms),
                color: cssVar('--status-p1', '#f59e0b'),
                area: true,
              },
              {
                name: 'P99',
                data: points.map((point) => point.p99_ms),
                color: cssVar('--status-p0', '#ef4444'),
              },
            ]}
          />
        </ChartPanel>

        <ChartPanel
          title="进程资源"
          hint="进程 CPU 与常驻内存；CPU 可能超过 100%（多线程）"
          hasCurve={hasCurve}
          interval={data.interval_seconds}
        >
          <MonitoringChart
            times={times}
            showSymbol={points.length <= 8}
            leftUnit="CPU %"
            rightUnit="MB"
            showRightAxis
            series={[
              {
                name: 'CPU %',
                data: points.map((point) => point.cpu_percent),
                color: cssVar('--status-p1', '#f59e0b'),
                area: true,
              },
              {
                name: '内存 MB',
                data: points.map((point) => point.memory_mb),
                color: cssVar('--accent-text', '#6da8e3'),
                axis: 1,
              },
            ]}
          />
        </ChartPanel>

        <ChartPanel
          title="检测活动"
          hint="每分钟跑了多少次任务、报了多少段告警"
          hasCurve={hasCurve}
          interval={data.interval_seconds}
        >
          <MonitoringChart
            times={times}
            showSymbol={points.length <= 8}
            leftUnit="次/分"
            series={[
              {
                name: '任务运行',
                data: points.map((point) => point.runs),
                color: cssVar('--accent-text', '#6da8e3'),
                area: true,
              },
              {
                name: '告警区间',
                data: points.map((point) => point.alerts),
                color: cssVar('--status-p0', '#ef4444'),
              },
            ]}
          />
        </ChartPanel>
      </div>

      <div className="monitoring__tables">
        <DetectorTable rows={data.detectors} />
        <StageTable rows={data.stages} />
        <RouteTable rows={data.http.routes} />
        <JobTable rows={data.jobs} />
      </div>
    </>
  )
}

interface ChartPanelProps {
  title: string
  hint: string
  hasCurve: boolean
  interval: number
  children: ReactNode
}

function ChartPanel({ title, hint, hasCurve, interval, children }: ChartPanelProps) {
  return (
    <section className="panel monitoring__panel">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">{title}</h2>
          <p className="panel__meta">{hint}</p>
        </div>
      </div>
      {hasCurve ? (
        children
      ) : (
        <p className="monitoring__empty">
          每 {interval} 秒记一个点，攒到两个点才有曲线。当前值见上方摘要。
        </p>
      )}
    </section>
  )
}

function DetectorTable({ rows }: { rows: ObservabilityDetectorRow[] }) {
  const columns: ColumnsType<ObservabilityDetectorRow> = [
    {
      title: '算法',
      dataIndex: 'detector',
      key: 'detector',
      render: (value: string) => detectorLabel(value),
    },
    {
      title: '调用',
      dataIndex: 'calls',
      key: 'calls',
      align: 'right',
      render: (value: number) => <span className="mono">{fmtNum(value)}</span>,
      sorter: (a, b) => a.calls - b.calls,
      defaultSortOrder: 'descend',
    },
    {
      title: '回退',
      dataIndex: 'fallbacks',
      key: 'fallbacks',
      align: 'right',
      render: (value: number) =>
        value > 0 ? <span className="mono mono--warn">{fmtNum(value)}</span> : <span className="dim">—</span>,
    },
    {
      title: '错误',
      dataIndex: 'errors',
      key: 'errors',
      align: 'right',
      render: (value: number) =>
        value > 0 ? <span className="mono mono--bad">{fmtNum(value)}</span> : <span className="dim">—</span>,
    },
    {
      title: '平均',
      dataIndex: 'avg_ms',
      key: 'avg_ms',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMs(value)}</span>,
    },
    {
      title: 'P95',
      dataIndex: 'p95_ms',
      key: 'p95_ms',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMs(value)}</span>,
    },
  ]

  return (
    <section className="panel monitoring__table">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">算法调用</h2>
          <p className="panel__meta">每条序列每跑一次算一次；回退是「推荐的算法不可用，换了兜底」</p>
        </div>
      </div>
      <Table
        rowKey="detector"
        columns={columns}
        dataSource={rows}
        size="small"
        pagination={false}
        locale={{ emptyText: '还没有算法调用' }}
      />
    </section>
  )
}

function StageTable({ rows }: { rows: ObservabilityStageRow[] }) {
  const columns: ColumnsType<ObservabilityStageRow> = [
    {
      title: '阶段',
      dataIndex: 'stage',
      key: 'stage',
      render: (value: string) => STAGE_LABELS[value] ?? value,
    },
    {
      title: '次数',
      dataIndex: 'count',
      key: 'count',
      align: 'right',
      render: (value: number) => <span className="mono">{fmtNum(value)}</span>,
    },
    {
      title: '平均',
      dataIndex: 'avg_ms',
      key: 'avg_ms',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMs(value)}</span>,
    },
    {
      title: 'P95',
      dataIndex: 'p95_ms',
      key: 'p95_ms',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMs(value)}</span>,
    },
  ]

  return (
    <section className="panel monitoring__table">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">任务阶段耗时</h2>
          <p className="panel__meta">一次运行拆成取数 / 检测 / 落盘，先看哪一段最贵</p>
        </div>
      </div>
      <Table
        rowKey="stage"
        columns={columns}
        dataSource={rows}
        size="small"
        pagination={false}
        locale={{ emptyText: '还没有任务运行' }}
      />
    </section>
  )
}

function RouteTable({ rows }: { rows: ObservabilityRouteRow[] }) {
  const columns: ColumnsType<ObservabilityRouteRow> = [
    {
      title: '接口',
      key: 'route',
      render: (_value, row) => (
        <div className="monitoring__route">
          <span className="mono dim">{row.method}</span>
          <span className="mono">{ROUTE_LABELS[row.route] ?? row.route}</span>
        </div>
      ),
    },
    {
      title: '次数',
      dataIndex: 'count',
      key: 'count',
      align: 'right',
      width: 80,
      render: (value: number) => <span className="mono">{fmtNum(value)}</span>,
      sorter: (a, b) => a.count - b.count,
      defaultSortOrder: 'descend',
    },
    {
      title: '错误',
      dataIndex: 'errors',
      key: 'errors',
      align: 'right',
      width: 70,
      render: (value: number) =>
        value > 0 ? <span className="mono mono--bad">{fmtNum(value)}</span> : <span className="dim">—</span>,
    },
    {
      title: '平均',
      dataIndex: 'avg_ms',
      key: 'avg_ms',
      align: 'right',
      width: 80,
      render: (value: number | null) => <span className="mono">{fmtMs(value)}</span>,
    },
    {
      title: 'P95',
      dataIndex: 'p95_ms',
      key: 'p95_ms',
      align: 'right',
      width: 80,
      render: (value: number | null) => <span className="mono">{fmtMs(value)}</span>,
    },
  ]

  return (
    <section className="panel monitoring__table monitoring__table--wide">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">接口性能</h2>
          <p className="panel__meta">
            按路由模板聚合，路径里的 {'{id}'} 不会各算一条
          </p>
        </div>
      </div>
      <Table
        rowKey={(row) => `${row.method} ${row.route}`}
        columns={columns}
        dataSource={rows.slice(0, 12)}
        size="small"
        pagination={false}
        locale={{ emptyText: '还没有接口调用' }}
      />
    </section>
  )
}

function JobTable({ rows }: { rows: ObservabilityJobRow[] }) {
  const columns: ColumnsType<ObservabilityJobRow> = [
    { title: '任务', dataIndex: 'job', key: 'job' },
    {
      title: '运行',
      dataIndex: 'runs',
      key: 'runs',
      align: 'right',
      render: (value: number) => <span className="mono">{fmtNum(value)}</span>,
      sorter: (a, b) => a.runs - b.runs,
      defaultSortOrder: 'descend',
    },
    {
      title: '失败',
      dataIndex: 'failed',
      key: 'failed',
      align: 'right',
      render: (value: number) =>
        value > 0 ? <span className="mono mono--bad">{fmtNum(value)}</span> : <span className="dim">—</span>,
    },
    {
      title: '数据不足',
      dataIndex: 'insufficient',
      key: 'insufficient',
      align: 'right',
      render: (value: number) =>
        value > 0 ? <span className="mono mono--warn">{fmtNum(value)}</span> : <span className="dim">—</span>,
    },
    {
      title: '平均',
      dataIndex: 'avg_ms',
      key: 'avg_ms',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMs(value)}</span>,
    },
    {
      title: 'P95',
      dataIndex: 'p95_ms',
      key: 'p95_ms',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMs(value)}</span>,
    },
  ]

  return (
    <section className="panel monitoring__table">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">任务执行</h2>
          <p className="panel__meta">试跑不计入 —— 这里只统计真正落库的运行</p>
        </div>
      </div>
      <Table
        rowKey="job"
        columns={columns}
        dataSource={rows}
        size="small"
        pagination={false}
        locale={{ emptyText: '还没有任务运行' }}
      />
    </section>
  )
}
