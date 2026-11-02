import { Link } from 'react-router-dom'
import { Button } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fmtUtcTime } from '../../lib/format'
import { getStorage, pruneData } from '../../api/platform'
import type { AlertEvent, Overview, OverviewJob, Summary } from '../../api/types'
import './overview.css'

/**
 * KPI 条 —— 只有字，没有卡片。
 *
 * ⚠️ 一个容器用 1px 分隔线切成几格，而不是每个数一张卡
 *    （app-screens §5：默认是一个容器切分隔线，不是每个 KPI 一张卡）。
 */
export function KpiStrip({
  overview,
  summary,
}: {
  overview: Overview
  summary: Summary | undefined
}) {
  const bt = summary?.summary?.overall
  return (
    <section className="kpis" aria-label="平台规模">
      <div className="kpi">
        <span className="kpi__k">检测任务</span>
        <span className="kpi__v mono">{overview.counts.jobs}</span>
        <span className="kpi__s">{overview.counts.enabled_jobs} 启用</span>
      </div>
      <div className="kpi">
        <span className="kpi__k">保留期运行</span>
        <span className="kpi__v mono">{overview.runs.total}</span>
        <span className="kpi__s">
          {overview.runs.failed > 0 ? `${overview.runs.failed} 失败` : '全部成功'}
        </span>
      </div>
      <div className="kpi">
        <span className="kpi__k">数据源 / 指标</span>
        <span className="kpi__v mono">
          {overview.counts.sources} / {overview.counts.metrics}
        </span>
        <span className="kpi__s">已接入平台</span>
      </div>
      <div className="kpi">
        <span className="kpi__k">人工反馈</span>
        <span className="kpi__v mono">{overview.feedback.total}</span>
        <span className="kpi__s">
          {overview.feedback.total > 0 ? '已标注的误报漏报' : '尚无标注'}
        </span>
      </div>
      <div className="kpi">
        <span className="kpi__k">回测序列</span>
        <span className="kpi__v mono">{bt?.n_series ?? '—'}</span>
        <span className="kpi__s">{bt ? `${bt.n_truth} 个真值点` : '还没有报告'}</span>
      </div>
    </section>
  )
}

/**
 * 告警事件 —— 当前选中序列的告警。
 *
 * ⚠️ 等级用 pill，序列不再每行重复 —— 序列在上面的切换条里已经写着。
 */
export function AlertEventsPanel({
  events,
  total,
  seriesId,
}: {
  events: AlertEvent[]
  total: number
  seriesId: string | undefined
}) {
  return (
    <section className="panel" aria-labelledby="eventsTitle">
      <div className="panel__head">
        <div>
          <h2 className="panel__title" id="eventsTitle">
            告警事件
          </h2>
          <p className="panel__meta mono">
            {seriesId ? `${seriesId} · ${events.length} 条` : `${events.length} 条`}
          </p>
        </div>
        <Link className="link" to="/alerts">
          全部 {total} 条
        </Link>
      </div>

      {events.length === 0 ? (
        <p className="muted">这个序列当前没有告警</p>
      ) : (
        <ul className="eventlist">
          {events.slice(0, 4).map((e) => (
            <li className="event" key={`${e.job_id}-${e.series_id}-${e.start_ts}`}>
              <span className={`pill pill--${e.level_index >= 2 ? 'p0' : 'p1'}`}>{e.level}</span>
              <span className="event__main">
                <span className="event__series mono">
                  {fmtUtcTime(e.start_ts)}
                  {e.end_ts !== e.start_ts ? ` – ${fmtUtcTime(e.end_ts).slice(6)}` : ''}
                </span>
                <span className="event__time mono">{e.detector}</span>
              </span>
              <span className="event__score">
                <span className="mono">{e.max_score.toFixed(2)}σ</span>
                <span className="event__pts mono">{e.n_points} 点</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="panel__foot">
        <span className="mono">
          {events.length > 4 ? `还有 ${events.length - 4} 条` : '本序列的告警'}
        </span>
        <Link className="link" to="/alerts">
          查看全部 {events.length} 条
        </Link>
      </div>
    </section>
  )
}

/**
 * 任务健康 —— 任务跑得怎么样、什么时候再跑。
 *
 * ⚠️ 「下次」来自 catalog 的 next_run_at —— 不拿 interval 自己推算，
 *    推算出来的下次运行时间可能是错的。
 */
export function JobHealthPanel({
  jobs,
  catalogJobs,
}: {
  jobs: OverviewJob[]
  catalogJobs: Array<{ id: number; interval_seconds: number; next_run_at: string | null }>
}) {
  const latest = jobs.find((j) => j.last_run)?.last_run ?? null
  const lastJob = jobs.find((j) => j.last_run?.n_series)

  return (
    <section className="panel" aria-labelledby="jobsTitle">
      <div className="panel__head">
        <div>
          <h2 className="panel__title" id="jobsTitle">
            任务运行状况
          </h2>
          <p className="panel__meta mono">{jobs.length} 个任务</p>
        </div>
        <Link className="link" to="/jobs">
          管理任务
        </Link>
      </div>

      <div className="jobhealth" role="table" aria-label="任务运行状况">
        <div className="jobrow jobrow--head" role="row">
          <span role="columnheader">任务</span>
          <span role="columnheader">最近一次</span>
          <span className="r" role="columnheader">
            序列
          </span>
          <span className="r" role="columnheader">
            告警
          </span>
          <span className="r jobrow__hide" role="columnheader">
            耗时
          </span>
          <span className="r jobrow__hide" role="columnheader">
            下次
          </span>
        </div>
        {jobs.map((job) => {
          const conf = catalogJobs.find((c) => c.id === job.id)
          const last = job.last_run
          const ok = last?.status === 'success'
          return (
            <div className="jobrow" role="row" key={job.id}>
              <span className="jobrow__name" role="cell">
                <b>
                  <Link to={`/jobs/${job.id}`}>{job.name}</Link>
                </b>
                <span className="mono">
                  {job.detector} · 每 {conf?.interval_seconds ?? '—'}s
                </span>
              </span>
              <span role="cell">
                {last ? (
                  <span className={`pill pill--${ok ? 'ok' : 'p0'}`} title={last.error ?? ''}>
                    {ok ? '成功' : '失败'}
                  </span>
                ) : (
                  <span className="muted">未运行</span>
                )}
              </span>
              <span className="r mono" role="cell">
                <span className="k">序列</span>
                {last?.n_series ?? '—'}
              </span>
              <span className="r mono" role="cell">
                <span className="k">告警</span>
                {last?.n_alerts ?? '—'}
              </span>
              <span className="r mono jobrow__hide" role="cell">
                <span className="k">耗时</span>
                {last ? fmtRunDuration(last.started_at, last.finished_at) : '—'}
              </span>
              <span className="r mono jobrow__hide" role="cell">
                <span className="k">下次</span>
                {conf?.next_run_at ? fmtUtcTime(conf.next_run_at).slice(6) : '—'}
              </span>
            </div>
          )
        })}
      </div>

      {latest && lastJob ? (
        <div className="runlog">
          <div className="runlog__head">
            <span>最近一次运行</span>
            <span className="mono">#{latest.id}</span>
          </div>
          <dl className="runlog__grid">
            <div>
              <dt>状态</dt>
              <dd>
                <span className={`pill pill--${latest.status === 'success' ? 'ok' : 'p0'}`}>
                  {latest.status === 'success' ? '成功' : '失败'}
                </span>
              </dd>
            </div>
            <div>
              <dt>序列</dt>
              <dd className="mono">{latest.n_series}</dd>
            </div>
            <div>
              <dt>告警</dt>
              <dd className="mono">{latest.n_alerts}</dd>
            </div>
            <div>
              <dt>耗时</dt>
              <dd className="mono">{fmtRunDuration(latest.started_at, latest.finished_at)}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </section>
  )
}

/** 运行时长。 */
export function fmtRunDuration(startedAt: string | null, finishedAt: string | null): string {
  if (!startedAt || !finishedAt) return '—'
  const start = Date.parse(startedAt)
  const end = Date.parse(finishedAt)
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

/**
 * 回测总体 —— 一个数（F1）领读，其余跟它并排。
 */
export function BacktestPanel({ summary }: { summary: Summary | undefined }) {
  const bt = summary?.summary?.overall
  if (!bt) {
    return (
      <section className="panel" aria-labelledby="btTitle">
        <div className="panel__head">
          <h2 className="panel__title" id="btTitle">
            回测总体
          </h2>
        </div>
        <p className="muted">还没有回测报告 —— 先跑一次评估。</p>
      </section>
    )
  }

  // 最差的一类形态 —— 「哪里最差」比「平均多好」更该被看见
  const classes = Object.entries(summary.summary.by_metric_class ?? {})
  const worst = classes
    .filter(([, bucket]) => bucket.n_series > 0)
    .sort((a, b) => a[1].f1 - b[1].f1)[0]

  return (
    <section className="panel" aria-labelledby="btTitle">
      <div className="panel__head">
        <div>
          <h2 className="panel__title" id="btTitle">
            回测总体
          </h2>
          <p className="panel__meta mono">
            {bt.n_series} 条序列 · {summary.generated_at?.slice(0, 10) ?? ''}
          </p>
        </div>
        <Link className="link" to="/evaluation">
          评估报告
        </Link>
      </div>

      <div className="backtest">
        <div className="backtest__lead">
          <span className="kpi__k">回测 F1</span>
          <span className="backtest__f1 mono">{bt.f1.toFixed(3)}</span>
          <span className="backtest__note">点级 F1，阈值逐条搜索</span>
        </div>
        <dl className="backtest__grid">
          <div>
            <dt>Precision</dt>
            <dd className="mono">{bt.precision.toFixed(3)}</dd>
          </div>
          <div>
            <dt>Recall</dt>
            <dd className="mono">{bt.recall.toFixed(3)}</dd>
          </div>
          <div>
            <dt>Range-F1</dt>
            <dd className="mono">{bt.range_f1.toFixed(3)}</dd>
          </div>
          <div>
            <dt>真值 / 预测</dt>
            <dd className="mono">
              {bt.n_truth.toLocaleString('en-US')} / {bt.n_pred.toLocaleString('en-US')}
            </dd>
          </div>
        </dl>
        {worst ? (
          <div className="backtest__finding">
            <span className="dot dot--p0" aria-hidden="true" />
            <p>
              <b>{worst[0]}</b> 形态最弱：{worst[1].n_series} 条序列 F1 为{' '}
              <span className="mono">{worst[1].f1.toFixed(3)}</span>，真值异常点{' '}
              <span className="mono">{worst[1].n_truth.toLocaleString('en-US')}</span> 个。
            </p>
            <Link className="link" to="/evaluation">
              看是哪几条
            </Link>
          </div>
        ) : null}
      </div>
    </section>
  )
}

/**
 * 数据保留 —— 占用、策略、上次清理。
 *
 * ⚠️ 「自动清理」如果完全不可见，用户没法判断它在不在工作。
 */
export function RetentionPanel() {
  const qc = useQueryClient()
  const storage = useQuery({ queryKey: ['storage'], queryFn: getStorage })
  const prune = useMutation({
    mutationFn: pruneData,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['storage'] })
      void qc.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  return (
    <section className="panel" aria-labelledby="retTitle">
      <div className="panel__head">
        <div>
          <h2 className="panel__title" id="retTitle">
            数据保留
          </h2>
          <p className="panel__meta mono">超出窗口的运行记录会被自动清掉</p>
        </div>
      </div>

      {storage.data ? (
        <div className="retention">
          <span className="retention__item">
            <span className="muted">运行记录</span>
            <span className="mono">{storage.data.runs.kept}</span>
            <span className="muted">条</span>
            <span className="mono">{fmtBytes(storage.data.runs.bytes)}</span>
          </span>
          <span className="retention__item">
            <span className="muted">保留策略</span>
            <span className="mono">最近 {storage.data.policy.retention_days} 天</span>
          </span>
          <span className="retention__item">
            <span className="muted">上次清理</span>
            <span>{storage.data.last_pruned_at ? sinceLabel(storage.data.last_pruned_at) : '还没清过'}</span>
          </span>
          <Button size="small" loading={prune.isPending} onClick={() => prune.mutate()}>
            立即清理
          </Button>
        </div>
      ) : (
        <p className="muted">{storage.isPending ? '加载中…' : '读不到存储占用'}</p>
      )}
    </section>
  )
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

/** 距上次清理多久。 */
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
