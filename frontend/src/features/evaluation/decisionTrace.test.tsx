import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DecisionTraceTimeline } from './DecisionTraceTimeline'

const fullTrace = {
  quality: { n: 500, n_missing: 0, zero_ratio: 0.976, n_nonzero: 12 },
  capability: {
    verdict: 'unsuitable',
    warnings: [{ detector: 'iqr', reason: '零值占 97.6%，IQR = 0' }],
  },
  classify: { metric_class: 'sparse_event', confidence: 0.91, reasons: [], candidates: [] },
  select: { detector: 'event_count', requested: 'auto', fallback: false, rationale: '' },
  threshold: { scale_source: 'poisson', status: 'ok', rules: [] },
  detect: { n_alerts: 26, n_p0: 3 },
}

describe('DecisionTraceTimeline', () => {
  it('渲染六段', () => {
    render(<DecisionTraceTimeline trace={fullTrace} />)
    for (const title of ['数据质量', '能力探测', '形态判断', '算法选择', '阈值与分级', '结果']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  it('摘要文字正确', () => {
    render(<DecisionTraceTimeline trace={fullTrace} />)
    expect(screen.getByText('500 点 · 零值 97.6% · 缺 0')).toBeInTheDocument()
    expect(screen.getByText('零值占 97.6%，IQR = 0')).toBeInTheDocument()
    expect(screen.getByText('稀疏事件型 / sparse_event（0.91）')).toBeInTheDocument()
    expect(screen.getByText('auto → event_count')).toBeInTheDocument()
    expect(screen.getByText('尺度 poisson · 正常')).toBeInTheDocument()
    expect(screen.getByText('26 个告警点 · 3 条 P0')).toBeInTheDocument()
  })

  it('能力不足时该步高亮', () => {
    render(<DecisionTraceTimeline trace={fullTrace} />)
    const warnings = document.querySelectorAll('.decision-trace__step--warn')
    expect(warnings).toHaveLength(1)
    expect(warnings[0].textContent).toContain('能力探测')
  })

  it('算法回退时该步高亮', () => {
    render(
      <DecisionTraceTimeline
        trace={{ select: { requested: 'auto', detector: 'iqr', fallback: true } }}
      />,
    )
    expect(screen.getByText('auto → iqr（回退）')).toBeInTheDocument()
    const warn = document.querySelector('.decision-trace__step--warn')
    expect(warn).not.toBeNull()
    expect(warn?.textContent).toContain('算法选择')
  })

  it('尺度判不出来时高亮', () => {
    render(
      <DecisionTraceTimeline
        trace={{ threshold: { scale_source: 'std', scale_fallback: false, status: 'undetermined' } }}
      />,
    )
    expect(screen.getByText('尺度 std · 无法判定')).toBeInTheDocument()
    const warn = document.querySelector('.decision-trace__step--warn')
    expect(warn).not.toBeNull()
    expect(warn?.textContent).toContain('阈值与分级')
  })

  it('尺度降级时高亮，摘要标出降级', () => {
    render(
      <DecisionTraceTimeline
        trace={{ threshold: { scale_source: 'std', scale_fallback: true, status: 'ok' } }}
      />,
    )
    expect(screen.getByText('尺度 std（降级） · 正常')).toBeInTheDocument()
    const warn = document.querySelector('.decision-trace__step--warn')
    expect(warn).not.toBeNull()
    expect(warn?.textContent).toContain('阈值与分级')
  })

  it('zscore 的原生 std 不算降级 —— 不高亮', () => {
    // ⚠️ zscore 的首选尺度就是 std，按 scale_source 判降级会把它每次标黄
    render(
      <DecisionTraceTimeline
        trace={{ threshold: { scale_source: 'std', scale_fallback: false, status: 'ok' } }}
      />,
    )
    expect(screen.getByText('尺度 std · 正常')).toBeInTheDocument()
    expect(document.querySelector('.decision-trace__step--warn')).toBeNull()
  })

  it('mad 暖机段退到 iqr 时高亮', () => {
    render(
      <DecisionTraceTimeline
        trace={{ threshold: { scale_source: 'iqr', scale_fallback: true, status: 'ok' } }}
      />,
    )
    expect(screen.getByText('尺度 iqr（降级） · 正常')).toBeInTheDocument()
    const warn = document.querySelector('.decision-trace__step--warn')
    expect(warn).not.toBeNull()
    expect(warn?.textContent).toContain('阈值与分级')
  })

  it('空决策链不渲染', () => {
    const { container } = render(<DecisionTraceTimeline trace={{}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('序号按固定步骤位置给，缺段不前移', () => {
    // ⚠️ 老数据可能缺中间某段；缺一步不该让后面的编号全部前移
    const { container } = render(
      <DecisionTraceTimeline trace={{ detect: { n_alerts: 1, n_p0: 0 } }} />,
    )
    const indexes = [...container.querySelectorAll('.decision-trace__index')].map(
      (node) => node.textContent,
    )
    expect(indexes).toEqual(['6'])
  })

  it('数据本身没问题但有形态不适配时，报数量且不高亮', () => {
    // ⚠️ 形态警告不参与 verdict —— 如果高亮，几乎所有非周期序列都会变成黄框
    render(
      <DecisionTraceTimeline
        trace={{
          capability: {
            verdict: 'ok',
            warnings: [],
            shape_warnings: [
              { detector: 'seasonal', reason: '没有可识别的周期' },
              { detector: 'stl_residual', reason: '没有可信周期' },
            ],
          },
        }}
      />,
    )
    expect(screen.getByText('2 项算法 × 形态适配风险')).toBeInTheDocument()
    expect(document.querySelector('.decision-trace__step--warn')).toBeNull()
  })
})
