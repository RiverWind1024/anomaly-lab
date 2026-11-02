import { useState } from 'react'
import { Button, message } from 'antd'
import { JobForm, buildJobPayload, type JobFormValues } from '../features/jobs/JobForm'
import { JobList } from '../features/jobs/JobList'
import { RecentRuns } from '../features/jobs/RecentRuns'
import { useCatalog, useCreateJob, useRunJob, useToggleJob } from '../features/jobs/queries'
import { useDeleteJob } from '../features/delete/queries'
import { useOverview } from '../features/overview/queries'

/** 任务列表页。 */
export function JobsPage() {
  const [formOpen, setFormOpen] = useState(false)

  const catalog = useCatalog()
  const overview = useOverview()
  const runJob = useRunJob()
  const toggleJob = useToggleJob()
  const createJob = useCreateJob()
  const deleteJob = useDeleteJob()

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

  const handleDelete = (jobId: number) => {
    deleteJob.mutate(jobId, {
      onSuccess: () => message.success('任务已删除'),
      onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
    })
  }

  const jobs = catalog.data?.jobs ?? []
  const enabled = jobs.filter((j) => j.enabled).length
  const overviewJobs = overview.data?.jobs ?? []
  const lastAlertJob = overviewJobs
    .filter((j) => j.last_run && j.last_run.n_alerts > 0)
    .sort((a, b) => (a.last_run?.id ?? 0) < (b.last_run?.id ?? 0) ? 1 : -1)[0]

  return (
    <div className="page">
      <header className="titlebar">
        <div className="titlebar__lead">
          <h1>检测任务</h1>
          <p className="finding">
            共 <span className="mono">{jobs.length}</span> 个任务 ·{' '}
            <span className="mono">{enabled}</span> 个启用
            {lastAlertJob?.last_run ? (
              <>
                {' '}
                —— <b>{lastAlertJob.name}</b> 上次跑出{' '}
                <span className="mono">{lastAlertJob.last_run.n_alerts}</span> 个告警点
              </>
            ) : null}
          </p>
        </div>
        <div className="titlebar__actions">
          <Button type="primary" onClick={() => setFormOpen(true)}>
            新建任务
          </Button>
        </div>
      </header>

      <JobList
        isLoading={catalog.isPending}
        error={catalog.error}
        catalog={catalog.data}
        overviewJobs={overviewJobs}
        runningJobId={runJob.isPending ? runJob.variables : null}
        togglingJobId={toggleJob.isPending ? toggleJob.variables?.jobId : null}
        onRun={handleRun}
        onToggle={handleToggle}
        onCreate={() => setFormOpen(true)}
        onDelete={handleDelete}
        deletingId={deleteJob.isPending ? (deleteJob.variables ?? null) : null}
      />

      {jobs.length > 0 ? (
        <RecentRuns
          jobs={jobs}
          defaultJobId={overviewJobs[0]?.id ?? jobs[0]?.id}
        />
      ) : null}

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
