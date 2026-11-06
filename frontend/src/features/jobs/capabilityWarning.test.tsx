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

  it('detector 为 auto 时把全部结论合成一条', () => {
    render(
      <CapabilityWarning
        detector="auto"
        capability={{
          verdict: 'unsuitable',
          warnings: [
            { detector: 'iqr', reason: 'IQR 退化为 0' },
            { detector: 'mad', reason: 'MAD 退化为 0' },
          ],
        }}
      />,
    )
    expect(screen.getByText(/IQR 退化为 0/)).toBeTruthy()
    expect(screen.getByText(/MAD 退化为 0/)).toBeTruthy()
  })
})
