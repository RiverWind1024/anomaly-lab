import { Link } from 'react-router-dom'
import { Space, Tag } from 'antd'
import type { CatalogJob, RunSummary } from '../../api/types'

export interface JobSummaryProps {
  job: CatalogJob
  metricName: string
  latestRun: RunSummary | undefined
  feedbackCount: number
}

/** 距上次运行多久（人类可读）。 */
export function sinceLabel(iso: string | null | undefined): string {
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

/**
 * 任务摘要卡。
 *
 * 「这个任务在干什么、跑到哪一步了」—— 一眼看完，
 * 细节各自去对应分区看。辅助信息只给数字 + 跳转，不在这里展开。
 */
export function JobSummary({ job, metricName, latestRun, feedbackCount }: JobSummaryProps) {
  return (
    <div className="job-summary">
      <Space size="large" wrap>
        <span>
          <span className="muted">检测指标</span>
          <Link to="/metrics" className="job-summary__value">
            {metricName}
          </Link>
        </span>
        <span>
          <span className="muted">检测序列</span>
          <span className="job-summary__value mono">{latestRun?.n_series ?? '—'}</span>
        </span>
        <span>
          <span className="muted">本次告警</span>
          <span className="job-summary__value mono">{latestRun?.n_alerts ?? '—'}</span>
        </span>
        <span>
          <span className="muted">最近运行</span>
          <span className="job-summary__value">{sinceLabel(latestRun?.started_at)}</span>
        </span>
        <span>
          <span className="muted">人工反馈</span>
          <Link to={`/jobs/${job.id}/feedback`} className="job-summary__value mono">
            {feedbackCount}
          </Link>
        </span>
        <span>
          <span className="muted">状态</span>
          <Tag color={job.enabled ? 'success' : 'default'}>
            {job.enabled ? '启用' : '停用'}
          </Tag>
        </span>
      </Space>
    </div>
  )
}
