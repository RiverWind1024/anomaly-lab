import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CatalogDetector } from '../../api/types'
import { JobForm } from './JobForm'
import { detectorLabel } from '../../lib/detectorLabels'

const detector = (over: Partial<CatalogDetector> = {}): CatalogDetector => ({
  name: 'iqr',
  default_threshold: 2.5,
  score_type: 'zscore',
  label: 'iqr',
  ...over,
})

function renderForm(detectors: CatalogDetector[]) {
  render(
    <JobForm
      open
      metrics={[]}
      detectors={detectors}
      onCancel={() => {}}
      onSubmit={() => {}}
    />,
  )
}

describe('算法下拉的可选性与标记', () => {
  it('不可用的算法显示「不可用」并被禁用', async () => {
    renderForm([
      detector(),
      detector({
        name: 'chronos',
        label: 'chronos',
        default_threshold: 0.5,
        score_type: 'prob',
        available: false,
        reason: 'chronos 未安装或本地无权重缓存',
      }),
    ])

    await userClickSelect(/检测算法/)
    expect(await screen.findByText(/不可用/)).toBeInTheDocument()
    // 不可用的项带 disabled
    const option = document.querySelector('.ant-select-item-option-disabled')
    expect(option?.textContent).toContain(detectorLabel('chronos'))
  })

  it('慢的算法标出「慢」', async () => {
    renderForm([
      detector({
        name: 'chronos',
        label: 'chronos',
        default_threshold: 0.5,
        score_type: 'prob',
        available: true,
        slow: true,
      }),
    ])

    await userClickSelect(/检测算法/)
    expect(await screen.findByText(/慢/)).toBeInTheDocument()
  })
})

/** 点开某个字段的下拉（AntD Select 不是原生 select）。 */
async function userClickSelect(label: RegExp) {
  const { default: userEvent } = await import('@testing-library/user-event')
  const user = userEvent.setup({ delay: null })
  await user.click(screen.getByLabelText(label))
}
