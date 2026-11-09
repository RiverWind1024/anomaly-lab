/**
 * 告警方向：默认双向、无基线算法禁用「只报偏低」、提交时带上方向。
 *
 * ⚠️ 背景：event_count / poisson_count 这类算法没有基线，只能报「偏高」。
 *    配成「只报偏低」等于让它一条都不报 —— 界面必须当场拦住，
 *    而不是等提交后看到「0 个告警点」以为一切正常。
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogDetector, CatalogMetric } from '../../api/types'
import { JobForm } from './JobForm'
import { detectorLabel } from '../../lib/detectorLabels'

const METRIC: CatalogMetric = {
  id: 1,
  source_id: 1,
  name: 'demo-metric',
  query: 'SELECT ts, value FROM m',
  time_column: 'ts',
  value_column: 'value',
  group_column: null,
  time_format: 'iso_utc',
  source_timezone: 'UTC',
  missing_policy: 'drop',
  created_at: '2026-10-30T00:00:00+00:00',
}

const IQR: CatalogDetector = {
  name: 'iqr',
  default_threshold: 2.5,
  score_type: 'zscore',
  label: 'iqr',
  direction: 'both',
}

/**
 * 无基线算法的占位 —— 真实对应 event_count / poisson_count。
 * 它们没有基线，只能报偏高，`direction` 为 `above`。
 */
const NO_BASELINE: CatalogDetector = {
  name: 'event_count',
  default_threshold: 3,
  score_type: 'zscore',
  label: 'event_count',
  direction: 'above',
}

function renderForm(onSubmit = vi.fn()) {
  render(
    <JobForm
      open
      metrics={[METRIC]}
      detectors={[IQR, NO_BASELINE]}
      onCancel={() => {}}
      onSubmit={onSubmit}
    />,
  )
  return onSubmit
}

/** 点开某个表单项的 Select，再点其中的选项。 */
async function pick(
  label: RegExp,
  optionText: string,
  user = userEvent.setup({ delay: null }),
) {
  await user.click(screen.getByLabelText(label))
  await user.click(await screen.findByText(optionText))
}

/** 当前「告警方向」选择框里显示的文字（下拉关闭后选项仍在 DOM 里）。 */
function directionSelectionText(): string | undefined {
  const item = [...document.querySelectorAll('.ant-form-item')].find((el) =>
    el.textContent?.includes('告警方向'),
  )
  return item?.querySelector('.ant-select-selection-item')?.textContent ?? undefined
}

describe('新建任务的告警方向', () => {
  it('默认选「双向」', () => {
    renderForm()
    expect(screen.getByText('双向（默认）')).toBeInTheDocument()
  })

  it('选了没有基线的算法后，「只报偏低」被禁用', async () => {
    const user = userEvent.setup({ delay: null })
    renderForm()

    await pick(/检测算法/, detectorLabel('event_count'), user)
    await waitFor(() =>
      expect(screen.getByText(/当前算法没有基线/)).toBeInTheDocument(),
    )

    await user.click(screen.getByLabelText(/告警方向/))
    const option = (await screen.findByText('只报偏低')).closest(
      '.ant-select-item-option',
    )
    expect(option?.className).toContain('ant-select-item-option-disabled')
  })

  it('从「只报偏低」切到无基线算法时自动改回「双向」', async () => {
    const user = userEvent.setup({ delay: null })
    renderForm()

    await pick(/告警方向/, '只报偏低', user)
    expect(directionSelectionText()).toBe('只报偏低')

    await pick(/检测算法/, detectorLabel('event_count'), user)

    await waitFor(() => expect(directionSelectionText()).toBe('双向（默认）'))
  })

  it('提交时 payload 带上告警方向', async () => {
    const user = userEvent.setup({ delay: null })
    const onSubmit = renderForm()

    await pick(/指标/, 'demo-metric', user)
    await user.type(screen.getByLabelText(/任务名称/), '方向测试')
    await pick(/检测算法/, detectorLabel('iqr'), user)
    await user.type(screen.getByLabelText(/执行间隔/), '300')
    await pick(/告警方向/, '只报偏高', user)
    await user.click(screen.getByRole('button', { name: /创\s*建/ }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit.mock.calls[0][0].alert_direction).toBe('above')
  }, 30000)
})
