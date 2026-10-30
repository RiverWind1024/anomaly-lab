import { useParams } from 'react-router-dom'
import { message } from 'antd'
import { PreviewPanel } from '../features/jobs/PreviewPanel'
import { usePreview, useRunJob } from '../features/jobs/queries'

/**
 * 任务详情页（预览部分）。
 *
 * Task 10~12 会补上运行记录下拉、序列切换、多算法对比、分类结论。
 */
export function JobDetailPage() {
  const params = useParams<{ jobId: string }>()
  const jobId = Number(params.jobId ?? 0)

  const preview = usePreview(jobId)
  const runJob = useRunJob()

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
