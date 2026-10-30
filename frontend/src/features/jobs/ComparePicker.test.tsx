import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ComparePicker } from './ComparePicker'

describe('ComparePicker 的慢算法标注', () => {
  it('标了 slow 的算法在勾选组里带「慢」后缀', () => {
    render(
      <ComparePicker
        available={['iqr', 'chronos']}
        fallbackNames={['iqr', 'chronos']}
        autoDetector="iqr"
        selected={[]}
        onChange={() => {}}
        detectors={[
          { name: 'iqr', default_threshold: 2.5, score_type: 'zscore', label: 'iqr' },
          {
            name: 'chronos',
            default_threshold: 0.5,
            score_type: 'prob',
            label: 'chronos',
            slow: true,
          },
        ]}
      />,
    )
    expect(screen.getByText('chronos（慢）')).toBeTruthy()
    expect(screen.getByText('iqr')).toBeTruthy()
  })
})
