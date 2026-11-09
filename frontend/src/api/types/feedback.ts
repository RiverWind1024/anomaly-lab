/** API 类型：人工反馈与调参建议。 */
// ─────────────────────────────────────────── 反馈 /api/platform/feedback

export type FeedbackKind = 'correct' | 'false_alarm' | 'missed' | 'other'

/** 注意字段是 start_ts / end_ts，不是 start / end。 */
export interface FeedbackRecord {
  id: number
  job_id: number
  run_id: number | null
  series_id: string
  start_ts: string
  end_ts: string
  kind: FeedbackKind
  note: string
  created_at: string
}

export interface FeedbackList {
  feedback: FeedbackRecord[]
}

export interface FeedbackIn {
  job_id: number
  series_id: string
  start_ts: string
  end_ts: string
  kind: FeedbackKind
  note?: string
  run_id?: number | null
}

// ─────────────────────────────────────────── 调参建议 /api/platform/jobs/{id}/feedback/suggestion

/** 某个告警倍数下的表现。缺正例/负例时对应指标是 `null`（不是 1.0）。 */
export interface ThresholdEvaluation {
  multiplier: number
  precision: number | null
  recall: number | null
  f1: number | null
  tp: number
  fp: number
  tn: number
  fn: number
}

export interface Suggestion {
  run_id: number | null
  /** 实际参与比较的算法（后端特意避开 candidates 这个键名）。 */
  evaluated_detectors: string[]
  current_detector: string
  suggested_detector: string
  detector_changed: boolean
  current_multiplier: number
  suggested_multiplier: number
  reason: string
  current: ThresholdEvaluation | null
  best: ThresholdEvaluation | null
  candidates: SuggestionCandidate[]
}

/** 候选设置的一行评估。字段与 ThresholdEvaluation 同构。 */
export type SuggestionCandidate = ThresholdEvaluation & {
  detector?: string
}

