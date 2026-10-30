import { useState } from 'react'
import { message } from 'antd'
import { JobForm, buildJobPayload, type JobFormValues } from '../features/jobs/JobForm'
import { JobList } from '../features/jobs/JobList'
import { useCatalog, useCreateJob, useRunJob, useToggleJob } from '../features/jobs/queries'

/** 任务列表页。 */
export function JobsPage() {
  const [formOpen, setFormOpen] = useState(false)

  const catalog = useCatalog()
  const runJob = useRunJob()
  const toggleJob = useToggleJob()
  const createJob = useCreateJob()

  const handleRun = (jobId: number) => {
    runJob.mutate(jobId, {
      onSuccess: () => message.success(`任务 ${jobId} 已触发立即运行`),
      onError: (err) => message.error(err instanceof Error ? err.message : '运行失败'),
    })
  }

  const handleToggle = (jobId: number, enabled: boolean) => {
    toggleJob.mutate(
      { jobId, payload: { enabled } },
      {
        onSuccess: () => message.success(`任务 ${jobId} 已${enabled ? '启用' : '停用'}`),
        onError: (err) => message.error(err instanceof Error ? err.message : '操作失败'),
      },
    )
  }

  const handleCreate = (values: JobFormValues) => {
    createJob.mutate(buildJobPayload(values), {
      onSuccess: () => {
        message.success(`任务「${values.name}」已创建`)
        setFormOpen(false)
      },
      onError: (err) => message.error(err instanceof Error ? err.message : '创建失败'),
    })
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">检测任务</h1>
        <p className="page__subtitle">
          {catalog.data ? `共 ${catalog.data.jobs.length} 个任务` : '加载中…'}
        </p>
      </header>

      <JobList
        isLoading={catalog.isPending}
        error={catalog.error}
        catalog={catalog.data}
        runningJobId={runJob.isPending ? runJob.variables : null}
        togglingJobId={toggleJob.isPending ? toggleJob.variables?.jobId : null}
        onRun={handleRun}
        onToggle={handleToggle}
        onCreate={() => setFormOpen(true)}
      />

      <JobForm
        open={formOpen}
        metrics={catalog.data?.metrics ?? []}
        detectors={catalog.data?.detectors ?? []}
        onCancel={() => setFormOpen(false)}
        onSubmit={handleCreate}
        submitting={createJob.isPending}
        error={createJob.error instanceof Error ? createJob.error.message : undefined}
      />
    </div>
  )
}
