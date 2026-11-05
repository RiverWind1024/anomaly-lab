import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button, message } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { getLabJobDraft } from '../api/platform'
import { JobForm, buildJobPayload, type JobFormInitialValues, type JobFormValues } from '../features/jobs/JobForm'
import { JobList } from '../features/jobs/JobList'
import { RecentRuns } from '../features/jobs/RecentRuns'
import { useCatalog, useCreateJob, useRunJob, useToggleJob } from '../features/jobs/queries'
import { useDeleteJob } from '../features/delete/queries'
import { useOverview } from '../features/overview/queries'

/** 任务列表页。 */
export function JobsPage() {
  const [formOpen, setFormOpen] = useState(false)
  const [params, setParams] = useSearchParams()

  /**
   * 「一键建任务」的落点 —— 从实验记录带 `experimentId` 跳过来。
   *
   * ⚠️ 草稿**先拿到再开表单** —— 否则表单会先以空值渲染，
   *    用户看到的是「没回填」的样子，再突然被内容覆盖。
   */
  const experimentId = params.get('experimentId')
  const draft = useQuery({
    queryKey: ['lab-job-draft', experimentId],
    queryFn: () => getLabJobDraft(experimentId as string),
    enabled: Boolean(experimentId),
  })

  useEffect(() => {
    if (draft.data) setFormOpen(true)
  }, [draft.data])

  /** 关闭表单时清掉 URL 里的实验 id —— 刷新不该又弹一次。 */
  const closeForm = () => {
    setFormOpen(false)
    if (experimentId) {
      const next = new URLSearchParams(params)
      next.delete('experimentId')
      setParams(next, { replace: true })
    }
  }

  const initialValues = useMemo<JobFormInitialValues | undefined>(
    () =>
      draft.data
        ? {
            metric_id: draft.data.metric_id,
            name: draft.data.name,
            detector: draft.data.detector,
            window_points: draft.data.window_points,
            interval_seconds: draft.data.interval_seconds,
            alert_rules: draft.data.alert_rules,
          }
        : undefined,
    [draft.data],
  )

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
        closeForm()
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
  const overviewJobs = overview.data?.jobs ?? []

  return (
    <div className="page">
      <header className="titlebar">
        <h1>告警任务</h1>
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
        onCancel={closeForm}
        onSubmit={handleCreate}
        submitting={createJob.isPending}
        error={createJob.error instanceof Error ? createJob.error.message : undefined}
        initialValues={initialValues}
        note={
          draft.data
            ? `已按实验 ${draft.data.experiment_id} 的结论预填：${draft.data.rationale}`
            : undefined
        }
      />
    </div>
  )
}
