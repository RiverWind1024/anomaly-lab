import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ScaleStatusTags } from './ScaleStatusTags'

describe('ScaleStatusTags', () => {
  it('status 为 undetermined 时显示「无法判定」', () => {
    render(<ScaleStatusTags status="undetermined" scaleSource="none" />)
    expect(screen.getByText('无法判定')).toBeTruthy()
  })

  it('scaleFallback 为 true 时显示降级来源', () => {
    render(<ScaleStatusTags status="ok" scaleSource="std" scaleFallback />)
    expect(screen.getByText('尺度降级 · std')).toBeTruthy()
  })

  it('都正常时不渲染任何标签', () => {
    const { container } = render(<ScaleStatusTags status="ok" scaleSource="mad" />)
    expect(container).toBeEmptyDOMElement()
  })
})
