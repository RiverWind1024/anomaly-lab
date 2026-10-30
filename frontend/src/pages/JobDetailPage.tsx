import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Tabs } from 'antd'
import { useCatalog, useFeedback, useRuns } from '../features/jobs/queries'
import { JobConfigPanel } from './job/JobConfigPanel'
import { JobDetectionsPanel } from './job/JobDetectionsPanel'
import { JobFeedbackPanel } from './job/JobFeedbackPanel'
import { JobRunsPanel } from './job/JobRunsPanel'
import { JobSummary } from './job/JobSummary'

/** 详情页的四个分区。各自独立成路由，不再挤在一页里。 */
export type JobSection = 'config' | 'runs' | 'detections' | 'feedback'

const SECTIONS: Array<{ key: JobSection; suffix: string; label: string }> = [
  { key: 'config', suffix: '', label: '任务配置' },
  { key: 'runs', suffix: '/runs', label: '运行记录' },
  { key: 'detections', suffix: '/detections', label: '检测结果' },
  { key: 'feedback', suffix: '/feedback', label: '人工反馈' },
]

/** 从路径判断当前分区。 */
export function sectionFromPath(pathname: string): JobSection {
  for (const item of SECTIONS) {
    if (item.suffix && pathname.endsWith(item.suffix)) return item.key
  }
  return 'config'
}

/**
 * 检测任务详情页 —— **布局壳**。
 *
 * 之前这一个页面把配置表单、运行记录、预览图、多算法对比、
 * 分类结论、反馈历史全堆在一起，什么都看不清楚。
 *
 * 现在：
 *   /jobs/:id              → 任务配置（主体）
 *   /jobs/:id/runs         → 运行记录
 *   /jobs/:id/detections   → 检测结果
 *   /jobs/:id/feedback     → 人工反馈
 *
 * 顶部摘要卡给出「在干什么、跑到哪一步」，细节各自去对应分区看。
 */
export function JobDetailPage() {
  const params = useParams<{ jobId: string }>()
  const jobId = Number(params.jobId ?? 0)
  const location = useLocation()
  const navigate = useNavigate()

  const section = sectionFromPath(location.pathname)

  const catalog = useCatalog()
  const job = catalog.data?.jobs.find((item) => item.id === jobId)
  const metric = catalog.data?.metrics.find((item) => item.id === job?.metric_id)

  // 任务不存在时**一个请求都不发** ——
  // 否则会刷出一屏红色错误框（runs / preview / compare / feedback / suggestion）。
  const jobExists = catalog.data ? job !== undefined : null
  const enabled = jobExists === true

  // 摘要卡要用的数据
  const runs = useRuns(jobId, enabled)
  const feedback = useFeedback(jobId, enabled)
  const latestRun = runs.data?.runs?.[0]

  // 「检测结果」分区默认看最近一次运行
  const effectiveRunId = latestRun?.id

  if (catalog.data && jobExists === false) {
    return (
      <div className="page">
        <header className="page__header">
          <h1 className="page__title">检测任务</h1>
          <p className="page__subtitle">任务 #{jobId}</p>
        </header>
        <div className="empty-state">
          <p className="empty-state__title">任务不存在或已被删除</p>
          <p className="muted">它可能刚被删掉了，或者链接里的编号不对。</p>
          <Link to="/jobs">← 回到检测任务列表</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">检测任务</h1>
        <p className="page__subtitle">
          {job ? job.name : `任务 #${jobId}`}
        </p>
      </header>

      {job ? (
        <JobSummary
          job={job}
          metricName={metric?.name ?? String(job.metric_id)}
          latestRun={latestRun}
          feedbackCount={feedback.data?.feedback?.length ?? 0}
        />
      ) : null}

      <Tabs
        className="job-tabs"
        activeKey={section}
        items={SECTIONS.map((item) => ({ key: item.key, label: item.label }))}
        onChange={(key) => {
          const target = SECTIONS.find((item) => item.key === key)
          navigate(`/jobs/${jobId}${target?.suffix ?? ''}`)
        }}
      />

      {section === 'config' && job ? (
        <JobConfigPanel
          job={job}
          metrics={catalog.data?.metrics ?? []}
          detectors={catalog.data?.detectors ?? []}
          enabled={enabled}
        />
      ) : null}

      {section === 'runs' ? <JobRunsPanel jobId={jobId} enabled={enabled} /> : null}

      {section === 'detections' ? (
        <JobDetectionsPanel
          jobId={jobId}
          runId={effectiveRunId}
          detectors={catalog.data?.detectors ?? []}
          enabled={enabled}
        />
      ) : null}

      {section === 'feedback' ? (
        <JobFeedbackPanel jobId={jobId} runId={effectiveRunId} enabled={enabled} />
      ) : null}
    </div>
  )
}
