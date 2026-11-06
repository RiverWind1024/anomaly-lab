import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CapabilityWarning } from './CapabilityWarning'

describe('CapabilityWarning', () => {
  it('命中所选算法时显示警告', () => {
    render(
      <CapabilityWarning
        detector="iqr"
        capability={{
          verdict: 'unsuitable',
          warnings: [{ detector: 'iqr', reason: '零值占 97.6%，Q3−Q1 = 0' }],
        }}
      />,
    )
    expect(screen.getByText(/零值占 97.6%/)).toBeTruthy()
  })

  it('警告不是当前算法时不显示', () => {
    const { container } = render(
      <CapabilityWarning
        detector="seasonal"
        capability={{ verdict: 'unsuitable', warnings: [{ detector: 'iqr', reason: 'x' }] }}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('没有 capability 时不渲染', () => {
    const { container } = render(<CapabilityWarning detector="iqr" capability={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('判定为 ok 时不渲染', () => {
    const { container } = render(
      <CapabilityWarning detector="iqr" capability={{ verdict: 'ok', warnings: [] }} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('尺度真的降级时，按尺度族命中复用该尺度的算法', () => {
    render(
      <CapabilityWarning
        detector="seasonal"
        preferScale="mad"
        scaleFallback
        capability={{
          verdict: 'unsuitable',
          warnings: [{ detector: 'mad', reason: 'MAD 退化为 0' }],
        }}
      />,
    )
    expect(screen.getByText(/MAD 退化为 0/)).toBeTruthy()
  })

  it('尺度没降级时，不按尺度族硬匹配', () => {
    const { container } = render(
      <CapabilityWarning
        detector="stl_residual"
        preferScale="mad"
        scaleFallback={false}
        capability={{
          verdict: 'unsuitable',
          warnings: [{ detector: 'mad', reason: 'MAD 退化为 0' }],
        }}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('说明文案不断言会退回标准差兜底', () => {
    render(
      <CapabilityWarning
        detector="zscore"
        capability={{
          verdict: 'unsuitable',
          warnings: [{ detector: 'zscore', reason: '零值占比过高' }],
        }}
      />,
    )
    expect(screen.getByText(/不符合该算法的假设/)).toBeInTheDocument()
    expect(screen.queryByText(/退回标准差兜底/)).not.toBeInTheDocument()
  })

  it('计数类算法 + 数据不是计数时提示', () => {
    render(
      <CapabilityWarning
        detector="poisson_count"
        capability={{ verdict: 'ok', warnings: [], count_ready: false }}
      />,
    )
    expect(screen.getByText(/要求非负整数计数/)).toBeTruthy()
  })

  it('计数类算法 + 数据是计数时不提示', () => {
    const { container } = render(
      <CapabilityWarning
        detector="event_count"
        capability={{ verdict: 'ok', warnings: [], count_ready: true }}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('非计数类算法不因 count_ready 提示', () => {
    const { container } = render(
      <CapabilityWarning
        detector="iqr"
        capability={{ verdict: 'ok', warnings: [], count_ready: false }}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('老产物没有 count_ready 时不误报', () => {
    const { container } = render(
      <CapabilityWarning
        detector="poisson_count"
        capability={{ verdict: 'ok', warnings: [] }}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
