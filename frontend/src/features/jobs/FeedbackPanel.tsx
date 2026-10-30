import { useEffect } from 'react'
import { Alert, Button, Form, Input, Select, Space, Tag } from 'antd'
import type { FeedbackKind, Suggestion, SuggestionCandidate } from '../../api/types'

export interface FeedbackPanelProps {
  /** 当前预览的序列（表单默认值） */
  seriesId?: string
  /** 当前预览的时间范围（表单默认值） */
  startTs?: string
  endTs?: string
  onSubmit: (values: FeedbackFormValues) => void
  submitting?: boolean
  error?: string
  suggestion?: Suggestion
  suggestionLoading?: boolean
  onEvaluate: () => void
  onApply: (suggestion: Suggestion) => void
  applying?: boolean
}

export interface FeedbackFormValues {
  series_id: string
  start_ts: string
  end_ts: string
  kind: FeedbackKind
  note: string
}

/** 反馈类型。取值必须是后端 `FeedbackIn.kind` 允许的那 4 个。 */
export const FEEDBACK_KIND_OPTIONS: Array<{ value: FeedbackKind; label: string }> = [
  { value: 'missed', label: '漏报（该报没报）' },
  { value: 'false_alarm', label: '误报（不该报却报了）' },
  { value: 'correct', label: '正确' },
  { value: 'other', label: '其他（不参与调参）' },
]

export const FEEDBACK_KIND_LABELS: Record<FeedbackKind, string> = {
  missed: '漏报',
  false_alarm: '误报',
  correct: '正确',
  other: '其他',
}

/**
 * 每个算法只留 F1 最好的那个候选。
 *
 * ⚠️ 后端会返回「算法 × 倍数」的完整网格（实测 5 个算法 × 17 个倍数 = 85 条），
 *    全列出来根本没法看。只留每个算法的最优项才有参考价值。
 */
export function bestCandidatePerDetector(
  candidates: SuggestionCandidate[],
): SuggestionCandidate[] {
  const best = new Map<string, SuggestionCandidate>()
  for (const candidate of candidates) {
    const key = candidate.detector ?? '(未标注算法)'
    const current = best.get(key)
    if (!current) {
      best.set(key, candidate)
      continue
    }
    const currentF1 = current.f1 ?? -1
    const candidateF1 = candidate.f1 ?? -1
    if (candidateF1 > currentF1) best.set(key, candidate)
  }
  return [...best.values()]
}

/**
 * 反馈面板：提交反馈 + 评估建议 + 一键应用。
 *
 * ⚠️ 提交时字段名是 `start_ts` / `end_ts`，且必须带 `job_id`
 *    （后端 `FeedbackIn` 要求）。
 */
export function FeedbackPanel({
  seriesId,
  startTs,
  endTs,
  onSubmit,
  submitting = false,
  error,
  suggestion,
  suggestionLoading = false,
  onEvaluate,
  onApply,
  applying = false,
}: FeedbackPanelProps) {
  const [form] = Form.useForm<FeedbackFormValues>()

  // 预览换了序列/时间范围 → 表单默认值跟着换（但不要覆盖用户已经改过的值）
  useEffect(() => {
    form.setFieldsValue({
      series_id: seriesId ?? '',
      start_ts: startTs ?? '',
      end_ts: endTs ?? '',
    })
  }, [seriesId, startTs, endTs, form])

  const handleOk = async () => {
    const values = await form.validateFields()
    onSubmit({
      ...values,
      series_id: values.series_id.trim(),
      start_ts: values.start_ts.trim(),
      end_ts: values.end_ts.trim(),
      note: values.note?.trim() ?? '',
    })
  }

  return (
    <div className="feedback-panel">
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}

      <Form form={form} layout="vertical" requiredMark="optional">
        <div className="feedback-panel__grid">
          <Form.Item
            name="series_id"
            label="序列"
            rules={[{ required: true, message: '请填写序列 ID' }]}
          >
            <Input placeholder="demo-metric:web-api" />
          </Form.Item>

          <Form.Item
            name="start_ts"
            label="开始时间"
            rules={[{ required: true, message: '请填写开始时间' }]}
          >
            <Input placeholder="2026-01-01T00:00:00" spellCheck={false} />
          </Form.Item>

          <Form.Item
            name="end_ts"
            label="结束时间"
            rules={[{ required: true, message: '请填写结束时间' }]}
          >
            <Input placeholder="2026-01-01T01:00:00" spellCheck={false} />
          </Form.Item>

          <Form.Item name="kind" label="类型" initialValue="missed">
            <Select options={FEEDBACK_KIND_OPTIONS} />
          </Form.Item>

          <Form.Item name="note" label="备注">
            <Input placeholder="可选" />
          </Form.Item>
        </div>

        <Space>
          <Button type="primary" loading={submitting} onClick={handleOk}>
            提交反馈
          </Button>
          <Button loading={suggestionLoading} onClick={onEvaluate}>
            评估并给建议
          </Button>
          {suggestion?.best && (
            <Button loading={applying} onClick={() => onApply(suggestion)}>
              应用建议倍数
            </Button>
          )}
        </Space>
      </Form>

      {suggestion && <SuggestionView suggestion={suggestion} />}
    </div>
  )
}

/**
 * 建议结果展示。
 *
 * `reason` 是后端给的中文说明，直接显示；
 * `suggested_multiplier` 与 `current_multiplier` 不同时高亮差异。
 */
export function SuggestionView({ suggestion }: { suggestion: Suggestion }) {
  const best = suggestion.best
  const fmt = (value: number | null | undefined) =>
    value === null || value === undefined ? '—' : value.toFixed(2)

  const multiplierChanged = suggestion.suggested_multiplier !== suggestion.current_multiplier

  return (
    <div className="suggestion">
      <p className="suggestion__reason">{suggestion.reason}</p>

      <Space size="large" wrap className="suggestion__metrics">
        {/* 倍数差异与换算法建议跟 best 无关 —— 没有 best 时也该显示 */}
        <span>
          倍数{' '}
          <span className={multiplierChanged ? 'mono suggestion__changed' : 'mono'}>
            {suggestion.current_multiplier}
            {multiplierChanged && ` → ${suggestion.suggested_multiplier}`}
          </span>
        </span>
        {suggestion.detector_changed && (
          <span>
            建议换算法{' '}
            <span className="mono">
              {suggestion.current_detector} → {suggestion.suggested_detector}
            </span>
          </span>
        )}
      </Space>

      {best && (
        <Space size="large" wrap className="suggestion__metrics">
          <span>
            precision <span className="mono">{fmt(best.precision)}</span>
          </span>
          <span>
            recall <span className="mono">{fmt(best.recall)}</span>
          </span>
          <span>
            F1 <span className="mono">{fmt(best.f1)}</span>
          </span>
        </Space>
      )}

      {!best && (
        <p className="muted suggestion__empty">
          还没有可用于评估的反馈 —— 提交「漏报」或「误报」后再点「评估并给建议」。
        </p>
      )}

      {suggestion.candidates.length > 0 && (
        <div className="suggestion__candidates">
          <p className="muted">各算法最优候选</p>
          <Space size="small" wrap>
            {bestCandidatePerDetector(suggestion.candidates).map((c) => (
              <Tag key={`${c.detector ?? ''}-${c.multiplier}`} className="mono">
                {c.detector ? `${c.detector} ` : ''}×{c.multiplier} · F1 {fmt(c.f1)}
              </Tag>
            ))}
          </Space>
        </div>
      )}
    </div>
  )
}
