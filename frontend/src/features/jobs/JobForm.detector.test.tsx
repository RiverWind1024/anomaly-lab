import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

describe('算法下拉的适用性说明', () => {
  it('选中带 guide 的算法后出现问号，切到没有 guide 的算法后消失', async () => {
    renderForm([
      detector({
        name: 'iqr',
        guide: { good_for: '平稳连续值', bad_for: '零值 > 75%' },
      }),
      detector({ name: 'mad', label: 'mad', default_threshold: 3.5 }),
    ])

    pickDetector('iqr')
    expect(await screen.findByLabelText('算法适用性')).toBeInTheDocument()

    pickDetector('mad')
    await waitFor(() =>
      expect(screen.queryByLabelText('算法适用性')).not.toBeInTheDocument(),
    )
  })
})

/** 点开「检测算法」下拉并选一个选项（AntD Select 不是原生 select）。 */
function pickDetector(name: string) {
  const item = [...document.querySelectorAll('.ant-form-item')].find((el) =>
    el.textContent?.includes('检测算法'),
  )
  expect(item, '找不到「检测算法」表单项').toBeTruthy()
  const select = item?.querySelector('.ant-select') as HTMLElement
  fireEvent.mouseDown(select.querySelector('.ant-select-selector') as HTMLElement)
  const option = [...document.querySelectorAll('.ant-select-item-option')].find((el) =>
    el.textContent?.startsWith(detectorLabel(name)),
  )
  expect(option, `找不到选项 ${name}`).toBeTruthy()
  fireEvent.click(option as HTMLElement)
}

/** 点开某个字段的下拉（AntD Select 不是原生 select）。 */
async function userClickSelect(label: RegExp) {
  const { default: userEvent } = await import('@testing-library/user-event')
  const user = userEvent.setup({ delay: null })
  await user.click(screen.getByLabelText(label))
}
