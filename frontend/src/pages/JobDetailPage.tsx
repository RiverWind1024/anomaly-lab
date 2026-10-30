import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { message } from 'antd'
import { CompareChart } from '../features/jobs/CompareChart'
import { ComparePicker } from '../features/jobs/ComparePicker'
import { CompareTable } from '../features/jobs/CompareTable'
import { ClassificationCard } from '../features/jobs/ClassificationCard'
import { FeedbackHistory } from '../features/jobs/FeedbackHistory'
import { FeedbackPanel, type FeedbackFormValues } from '../features/jobs/FeedbackPanel'
import { PreviewPanel } from '../features/jobs/PreviewPanel'
import { RunsView, SeriesSelect } from '../features/jobs/RunsView'
import {
  useApplySuggestion,
  useCatalog,
  useCompare,
  useCreateFeedback,
  useFeedback,
  usePreview,
  useRunJob,
  useRuns,
  useSuggestion,
  useToggleJob,
} from '../features/jobs/queries'
import type { Suggestion } from '../api/types'

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
  // 对比勾选的算法；留空 = 用默认勾选（候选 ≤4 全勾，否则只勾 auto）
  const [detectors, setDetectors] = useState<string[]>([])

  const catalog = useCatalog()
  const runs = useRuns(jobId)
  const preview = usePreview(jobId, runId, seriesId)
  const compare = useCompare(jobId, seriesId, detectors)
  const runJob = useRunJob()
  const toggleJob = useToggleJob()
  const feedback = useFeedback(jobId)
  const createFeedback = useCreateFeedback()
  const applySuggestion = useApplySuggestion(jobId)

  // 下拉要显示一个具体的值：没手动选过时用最新运行 / 后端挑中的序列
  const effectiveRunId = runId ?? runs.data?.runs[0]?.id
  const effectiveSeriesId = seriesId ?? preview.data?.series_id

  // 建议要按选中的那次运行评估
  const suggestion = useSuggestion(jobId, effectiveRunId)

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

  const handleApplyDetector = (name: string) => {
    toggleJob.mutate(
      { jobId, payload: { detector: name } },
      {
        onSuccess: () => message.success(`任务 ${jobId} 的算法已设为 ${name}`),
        onError: (err) => message.error(err instanceof Error ? err.message : '设置失败'),
      },
    )
  }

  const handleSubmitFeedback = (values: FeedbackFormValues) => {
    createFeedback.mutate(
      {
        job_id: jobId,
        series_id: values.series_id,
        start_ts: values.start_ts,
        end_ts: values.end_ts,
        kind: values.kind,
        note: values.note,
        run_id: effectiveRunId ?? null,
      },
      {
        onSuccess: () => message.success('反馈已提交'),
        onError: (err) => message.error(err instanceof Error ? err.message : '提交失败'),
      },
    )
  }

  const handleApplySuggestion = (s: Suggestion) => {
    applySuggestion.mutate(
      { multiplier: s.suggested_multiplier, detector: s.suggested_detector },
      {
        onSuccess: () => message.success('建议已应用，新的告警倍数见任务列表'),
        onError: (err) => message.error(err instanceof Error ? err.message : '应用失败'),
      },
    )
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

      <section className="compare-section">
        <h2 className="section__title">多算法对比</h2>
        <ComparePicker
          available={compare.data?.available ?? []}
          fallbackNames={(catalog.data?.detectors ?? []).map((d) => d.name)}
          autoDetector={compare.data?.auto_detector ?? 'auto'}
          selected={detectors}
          onChange={setDetectors}
        />

        {compare.data && (
          <>
            <ClassificationCard
              metricClass={compare.data.metric_class ?? ''}
              confidence={compare.data.confidence ?? 0}
              reasons={compare.data.reasons}
              autoDetector={compare.data.auto_detector}
              autoRationale={compare.data.auto_rationale}
              autoFallback={compare.data.auto_fallback}
              /* 分数类型要取 **auto 选中的那个算法** 的 ——
                 卡片讲的是 auto 推荐，不能拿 detectors[0] 的（顺序不保证是 auto）。 */
              scoreType={
                compare.data.detectors.find((d) => d.is_auto)?.score_type ??
                compare.data.detectors[0]?.score_type ??
                ''
              }
            />
            <CompareChart
              timestamps={compare.data.timestamps}
              values={compare.data.values}
              detectors={compare.data.detectors}
            />
            <CompareTable
              detectors={compare.data.detectors}
              levels={compare.data.levels}
              applyingDetector={
                toggleJob.isPending ? toggleJob.variables?.payload.detector ?? null : null
              }
              onApplyDetector={handleApplyDetector}
            />
          </>
        )}
      </section>

      <section className="feedback-section">
        <h2 className="section__title">人工反馈与调参</h2>
        <p className="muted feedback-section__hint">
          反馈用于给出「用哪个算法 + 用哪个倍数」的建议 ——
          漏报与误报才参与调参，「正确」「其他」只留档。
        </p>

        <FeedbackPanel
          seriesId={effectiveSeriesId}
          startTs={preview.data?.timestamps[0]}
          endTs={preview.data?.timestamps[preview.data.timestamps.length - 1]}
          onSubmit={handleSubmitFeedback}
          submitting={createFeedback.isPending}
          error={createFeedback.error instanceof Error ? createFeedback.error.message : undefined}
          suggestion={suggestion.data}
          suggestionLoading={suggestion.isPending || suggestion.isFetching}
          onEvaluate={() => void suggestion.refetch()}
          onApply={handleApplySuggestion}
          applying={applySuggestion.isPending}
        />

        <FeedbackHistory
          isLoading={feedback.isPending}
          error={feedback.error}
          feedback={feedback.data?.feedback}
        />
      </section>
    </div>
  )
}
