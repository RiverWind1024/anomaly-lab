import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { FeedbackRecord, Suggestion, SuggestionCandidate } from '../../api/types'
import { FeedbackHistory } from './FeedbackHistory'
import {
  FEEDBACK_KIND_LABELS,
  FEEDBACK_KIND_OPTIONS,
  FeedbackPanel,
  SuggestionView,
  bestCandidatePerDetector,
} from './FeedbackPanel'

const record = (over: Partial<FeedbackRecord> = {}): FeedbackRecord => ({
  id: 1,
  job_id: 1,
  run_id: 3,
  series_id: 'demo-metric:web-api',
  start_ts: '2026-10-29T05:57:00',
  end_ts: '2026-10-29T07:57:00',
  kind: 'missed',
  note: '这里应该报',
  created_at: '2026-10-30T03:00:00+00:00',
  ...over,
})

const suggestion = (over: Partial<Suggestion> = {}): Suggestion => ({
  run_id: 3,
  evaluated_detectors: ['iqr', 'seasonal'],
  current_detector: 'seasonal',
  suggested_detector: 'seasonal',
  detector_changed: false,
  current_multiplier: 2.5,
  suggested_multiplier: 2.5,
  reason: '反馈样本不足',
  current: null,
  best: null,
  candidates: [],
  ...over,
})

describe('反馈类型选项', () => {
  it('取值与后端 FEEDBACK_KINDS 完全一致', () => {
    // 后端：{"correct", "false_alarm", "missed", "other"}
    expect(FEEDBACK_KIND_OPTIONS.map((o) => o.value).sort()).toEqual([
      'correct',
      'false_alarm',
      'missed',
      'other',
    ])
  })

  it('每个类型都有中文标签', () => {
    for (const option of FEEDBACK_KIND_OPTIONS) {
      expect(FEEDBACK_KIND_LABELS[option.value]).toBeTruthy()
    }
  })
})

describe('FeedbackHistory', () => {
  it('空列表显示空态', () => {
    render(<FeedbackHistory isLoading={false} error={null} feedback={[]} />)
    expect(screen.getByText('还没有反馈记录')).toBeTruthy()
  })

  it('渲染 ID / 序列 / 时间范围 / 类型 / 备注', () => {
    render(<FeedbackHistory isLoading={false} error={null} feedback={[record()]} />)
    // 「1」既出现在 ID 单元格也出现在分页器里 —— 只查表格里的那一处
    const cells = screen.getAllByRole('cell')
    expect(cells[0].textContent).toBe('1')
    expect(screen.getByText('demo-metric:web-api')).toBeTruthy()
    expect(screen.getByText(/2026-10-29 13:57:00 ~ 2026-10-29 15:57:00/)).toBeTruthy()
    expect(screen.getByText('漏报')).toBeTruthy()
    expect(screen.getByText('这里应该报')).toBeTruthy()
  })

  it('无备注时显示占位', () => {
    render(<FeedbackHistory isLoading={false} error={null} feedback={[record({ note: '' })]} />)
    expect(screen.getByText('—')).toBeTruthy()
  })
})

describe('SuggestionView', () => {
  it('显示后端给的中文 reason', () => {
    render(<SuggestionView suggestion={suggestion({ reason: '漏报偏多，建议放宽阈值' })} />)
    expect(screen.getByText('漏报偏多，建议放宽阈值')).toBeTruthy()
  })

  it('没有 best 时提示还需要反馈', () => {
    render(<SuggestionView suggestion={suggestion()} />)
    expect(screen.getByText(/还没有可用于评估的反馈/)).toBeTruthy()
  })

  it('有 best 时显示 precision / recall / F1', () => {
    render(
      <SuggestionView
        suggestion={suggestion({
          best: {
            multiplier: 3,
            precision: 0.8,
            recall: 0.6,
            f1: 0.6857,
            tp: 3,
            fp: 1,
            tn: 10,
            fn: 2,
          },
        })}
      />,
    )
    expect(screen.getByText('0.80')).toBeTruthy()
    expect(screen.getByText('0.60')).toBeTruthy()
    expect(screen.getByText('0.69')).toBeTruthy()
  })

  it('倍数变化时把差异显示出来', () => {
    render(
      <SuggestionView
        suggestion={suggestion({ current_multiplier: 2.5, suggested_multiplier: 3.5 })}
      />,
    )
    expect(screen.getByText('2.5 → 3.5')).toBeTruthy()
  })

  it('倍数没变时不显示箭头', () => {
    render(<SuggestionView suggestion={suggestion()} />)
    expect(screen.queryByText(/→/)).toBeNull()
  })

  it('建议换算法时显示算法变化', () => {
    render(
      <SuggestionView
        suggestion={suggestion({
          detector_changed: true,
          current_detector: 'seasonal',
          suggested_detector: 'iqr',
        })}
      />,
    )
    expect(screen.getByText('seasonal → iqr')).toBeTruthy()
  })

  it('指标缺失时显示「—」而不是 NaN', () => {
    render(
      <SuggestionView
        suggestion={suggestion({
          best: {
            multiplier: 3,
            precision: null,
            recall: null,
            f1: null,
            tp: 0,
            fp: 0,
            tn: 0,
            fn: 0,
          },
        })}
      />,
    )
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('NaN')).toBeNull()
  })
})

describe('bestCandidatePerDetector', () => {
  const candidate = (
    detector: string | undefined,
    multiplier: number,
    f1: number | null,
  ): SuggestionCandidate => ({
    multiplier,
    precision: null,
    recall: null,
    f1,
    tp: 0,
    fp: 0,
    tn: 0,
    fn: 0,
    ...(detector ? { detector } : {}),
  })

  it('每个算法只留 F1 最高的那个', () => {
    const result = bestCandidatePerDetector([
      candidate('iqr', 2.5, 0.31),
      candidate('iqr', 0.1, 0.98),
      candidate('iqr', 1, 0.71),
      candidate('seasonal', 2.5, 0.9),
      candidate('seasonal', 3, 0.7),
    ])
    expect(result).toHaveLength(2)
    expect(result.find((c) => c.detector === 'iqr')?.multiplier).toBe(0.1)
    expect(result.find((c) => c.detector === 'seasonal')?.multiplier).toBe(2.5)
  })

  it('F1 为 null 时不当作最优（null 与 -1 比较）', () => {
    const result = bestCandidatePerDetector([
      candidate('iqr', 2.5, null),
      candidate('iqr', 1, 0.5),
    ])
    expect(result).toHaveLength(1)
    expect(result[0].multiplier).toBe(1)
  })

  it('没有 detector 字段的归到同一组', () => {
    const result = bestCandidatePerDetector([
      candidate(undefined, 2.5, 0.3),
      candidate(undefined, 1, 0.6),
    ])
    expect(result).toHaveLength(1)
    expect(result[0].multiplier).toBe(1)
  })

  it('空数组返回空', () => {
    expect(bestCandidatePerDetector([])).toEqual([])
  })
})

describe('FeedbackPanel', () => {
  it('渲染表单字段与按钮', () => {
    render(
      <FeedbackPanel
        seriesId="demo-metric:web-api"
        startTs="2026-10-29T05:57:00"
        endTs="2026-10-29T07:57:00"
        onSubmit={() => {}}
        onEvaluate={() => {}}
        onApply={() => {}}
      />,
    )
    expect(screen.getByText('序列')).toBeTruthy()
    expect(screen.getByText('开始时间')).toBeTruthy()
    expect(screen.getByText('结束时间')).toBeTruthy()
    expect(screen.getByText('类型')).toBeTruthy()
    expect(screen.getByText('备注')).toBeTruthy()
    expect(screen.getByText('提交反馈')).toBeTruthy()
    expect(screen.getByText('评估并给建议')).toBeTruthy()
  })

  it('没有 best 时不显示「应用建议倍数」按钮', () => {
    render(
      <FeedbackPanel
        seriesId="s"
        onSubmit={() => {}}
        onEvaluate={() => {}}
        onApply={() => {}}
        suggestion={suggestion()}
      />,
    )
    expect(screen.queryByText('应用建议倍数')).toBeNull()
  })

  it('有 best 时显示「应用建议倍数」按钮', () => {
    render(
      <FeedbackPanel
        seriesId="s"
        onSubmit={() => {}}
        onEvaluate={() => {}}
        onApply={() => {}}
        suggestion={suggestion({
          best: {
            multiplier: 3,
            precision: 0.8,
            recall: 0.6,
            f1: 0.7,
            tp: 1,
            fp: 0,
            tn: 1,
            fn: 0,
          },
        })}
      />,
    )
    expect(screen.getByText('应用建议倍数')).toBeTruthy()
  })
})
