import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AlgorithmGuide } from './AlgorithmGuide'

describe('AlgorithmGuide', () => {
  it('有说明时渲染问号图标', () => {
    render(<AlgorithmGuide guide={{ good_for: '平稳连续值', bad_for: '零值 >75%' }} />)
    expect(screen.getByLabelText('算法适用性')).toBeInTheDocument()
  })

  it('没有说明时什么都不渲染', () => {
    const { container } = render(<AlgorithmGuide guide={{}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('只有 bad_for 时不渲染空的「适合」行', () => {
    render(<AlgorithmGuide guide={{ bad_for: '零值 >75%' }} />)
    expect(screen.queryByText('适合')).not.toBeInTheDocument()
  })
})
