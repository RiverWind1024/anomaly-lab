import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogDetector, CatalogMetric } from '../../api/types'
import { JobForm } from './JobForm'
import { INTERVAL_SECONDS_MIN, WINDOW_POINTS_MAX, WINDOW_POINTS_MIN } from './limits'

const detector: CatalogDetector = {
  name: 'iqr',
  default_threshold: 2.5,
  score_type: 'zscore',
  label: 'iqr',
}

const metric: CatalogMetric = {
  id: 1,
  source_id: 1,
  name: 'demo-metric',
  query: 'SELECT ts, value FROM m',
  time_column: 'ts',
  value_column: 'value',
  group_column: null,
  time_format: 'iso_utc',
  freq: '5min',
  source_timezone: 'UTC',
  missing_policy: 'drop',
  created_at: '2026-10-30T00:00:00+00:00',
}

function renderJobForm(onSubmit = vi.fn()) {
  render(
    <JobForm
      open
      metrics={[metric]}
      detectors={[detector]}
      onCancel={() => {}}
      onSubmit={onSubmit}
    />,
  )
  return onSubmit
}

describe('新建任务表单的数值下限提示', () => {
  it('窗口点数与执行间隔都写出后端下限', async () => {
    renderJobForm()
    expect(await screen.findByText(new RegExp(`至少 ${WINDOW_POINTS_MIN} 点`))).toBeInTheDocument()
    expect(await screen.findByText(new RegExp(`至少 ${INTERVAL_SECONDS_MIN} 秒`))).toBeInTheDocument()
  })

  it('下限常量与后端 validation.py 一致（10 / 100000 / 10）', () => {
    expect(WINDOW_POINTS_MIN).toBe(10)
    expect(WINDOW_POINTS_MAX).toBe(100_000)
    expect(INTERVAL_SECONDS_MIN).toBe(10)
  })
})

describe('新建任务表单的即时校验', () => {
  it('窗口点数低于下限时会被当场钳到下限', async () => {
    renderJobForm()
    // delay: null —— AntD 的受控输入每次按键都要等一轮渲染，默认延迟会超时
    const user = userEvent.setup({ delay: null })

    const windowInput = screen.getByLabelText(/窗口点数/)
    await user.type(windowInput, '5')
    await user.tab() // 失焦 → InputNumber 按 min 钳制

    // InputNumber 的 input 是 type=text，值是字符串
    await waitFor(() => expect(windowInput).toHaveValue(String(WINDOW_POINTS_MIN)))
  })

  it('必填项没填时拦下提交，不等后端 400', async () => {
    const onSubmit = renderJobForm()
    const user = userEvent.setup({ delay: null })

    // AntD 的 Select 不是原生 <select>，只能点开下拉再选选项
    await user.click(screen.getByLabelText(/指标/))
    await user.click(await screen.findByTitle('demo-metric'))
    await user.type(screen.getByLabelText(/任务名称/), 'j')
    await user.click(screen.getByLabelText(/检测算法/))
    await user.click(await screen.findByTitle('iqr'))
    // AntD 给两个汉字的按钮自动插空格（"创 建"），用正则匹配
    await user.click(screen.getByRole('button', { name: /创\s*建/ }))

    await waitFor(() => {
      expect(screen.getByText('请输入执行间隔')).toBeInTheDocument()
    })
    expect(onSubmit).not.toHaveBeenCalled()
  }, 20000)
})
