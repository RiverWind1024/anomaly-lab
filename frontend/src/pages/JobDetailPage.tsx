import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { message } from 'antd'
import { PreviewPanel } from '../features/jobs/PreviewPanel'
import { RunsView, SeriesSelect } from '../features/jobs/RunsView'
import { usePreview, useRunJob, useRuns } from '../features/jobs/queries'

/**
 * 任务详情页（预览部分）。
 *
 * Task 10~12 会补上运行记录下拉、序列切换、多算法对比、分类结论。
 */
export function JobDetailPage() {
  const params = useParams<{ jobId: string }>()
  const jobId = Number(params.jobId ?? 0)

  // runId / seriesId 留空 = 不带参数，后端会取最新运行与首个序列
  const [runId, setRunId] = useState<number | undefined>(undefined)
  const [seriesId, setSeriesId] = useState<string | undefined>(undefined)

  const runs = useRuns(jobId)
  const preview = usePreview(jobId, runId, seriesId)
  const runJob = useRunJob()

  // 下拉要显示一个具体的值：没手动选过时用最新运行 / 后端挑中的序列
  const effectiveRunId = runId ?? runs.data?.runs[0]?.id
  const effectiveSeriesId = seriesId ?? preview.data?.series_id

  /**
   * 换运行要清掉序列选择 —— 每次运行的序列集合不同，
   * 带着旧 series_id 请求会拿到 404「序列不存在」。
   */
  const handleSelectRun = (nextRunId: number) => {
    setRunId(nextRunId)
    setSeriesId(undefined)
  }

  const handleRun = () => {
    runJob.mutate(jobId, {
      onSuccess: () => message.success(`任务 ${jobId} 已触发立即运行`),
      onError: (err) => message.error(err instanceof Error ? err.message : '运行失败'),
    })
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">检测任务 · 详情与预览</h1>
        <p className="page__subtitle">任务 #{jobId}</p>
      </header>

      <div className="runs-view__bar">
        <RunsView
          runs={runs.data?.runs ?? []}
          selectedRunId={effectiveRunId}
          onSelect={handleSelectRun}
          loading={runs.isPending}
        />
        <SeriesSelect
          series={preview.data?.series ?? []}
          selectedSeriesId={effectiveSeriesId}
          onSelect={setSeriesId}
          loading={preview.isPending}
        />
      </div>

      <PreviewPanel
        isLoading={preview.isPending}
        error={preview.error}
        preview={preview.data}
        onRun={handleRun}
        running={runJob.isPending}
      />
    </div>
  )
}
