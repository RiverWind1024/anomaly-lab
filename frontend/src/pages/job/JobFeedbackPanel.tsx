import { message } from 'antd'
import { FeedbackHistory } from '../../features/jobs/FeedbackHistory'
import { FeedbackPanel, type FeedbackFormValues } from '../../features/jobs/FeedbackPanel'
import {
  useApplySuggestion,
  useCreateFeedback,
  useFeedback,
  usePreview,
  useSuggestion,
} from '../../features/jobs/queries'
import type { Suggestion } from '../../api/types'

export interface JobFeedbackPanelProps {
  jobId: number
  runId?: number
  enabled: boolean
}

/**
 * 人工反馈与调参面板。
 *
 * 反馈用于给出「用哪个算法 + 用哪个倍数」的建议 ——
 * 漏报与误报才参与调参，「正确」「其他」只留档。
 */
export function JobFeedbackPanel({ jobId, runId, enabled }: JobFeedbackPanelProps) {
  const preview = usePreview(jobId, runId, undefined, enabled)
  const feedback = useFeedback(jobId, enabled)
  const createFeedback = useCreateFeedback()
  const suggestion = useSuggestion(jobId, runId, enabled)
  const applySuggestion = useApplySuggestion(jobId)

  const effectiveSeriesId = preview.data?.series_id

  const handleSubmitFeedback = (values: FeedbackFormValues) => {
    createFeedback.mutate(
      {
        job_id: jobId,
        series_id: values.series_id,
        start_ts: values.start_ts,
        end_ts: values.end_ts,
        kind: values.kind,
        note: values.note,
        run_id: runId ?? null,
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
        onSuccess: () => message.success('建议已应用，新的告警倍数见任务配置'),
        onError: (err) => message.error(err instanceof Error ? err.message : '应用失败'),
      },
    )
  }

  return (
    <div className="job-feedback">
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
    </div>
  )
}
