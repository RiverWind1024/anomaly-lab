import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogDetector, CatalogMetric } from '../../api/types'
import { JobForm, buildJobPayload, type JobFormValues } from './JobForm'
import {
  INTERVAL_SECONDS_MIN,
  WINDOW_SECONDS_MAX,
  WINDOW_SECONDS_MIN,
  WINDOW_UNIT_SECONDS,
  splitWindow,
} from './limits'

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

describe('新建任务表单的时间窗口', () => {
  it('窗口时长由控件守住下限，单位可选', async () => {
    renderJobForm()
    const valueInput = screen.getByLabelText('窗口时长')
    expect(valueInput).toHaveAttribute('aria-valuemin', '1')
    expect(screen.getAllByLabelText('窗口单位').length).toBeGreaterThan(0)

    const intervalInput = screen.getByLabelText(/执行间隔/)
    expect(intervalInput).toHaveAttribute('aria-valuemin', String(INTERVAL_SECONDS_MIN))
  })

  it('窗口按「数值 × 单位」换算成秒', () => {
    expect(WINDOW_SECONDS_MIN).toBe(60)
    expect(WINDOW_SECONDS_MAX).toBe(365 * 86400)
    expect(WINDOW_UNIT_SECONDS.hour).toBe(3600)
    // 回填：整天的秒数用「天」，否则退回分钟
    expect(splitWindow(86400)).toEqual({ window_value: 1, window_unit: 'day' })
    expect(splitWindow(1800)).toEqual({ window_value: 30, window_unit: 'minute' })
  })
})

describe('检测点数', () => {
  it('缺省按 0 提交，窗口换算成秒', () => {
    const base = {
      metric_id: 1,
      name: 'j',
      detector: 'iqr',
      window_value: 1,
      window_unit: 'day' as const,
      interval_seconds: 60,
      alert_rules: null,
      alert_direction: 'both' as const,
    }
    const payload = buildJobPayload({ ...base, detect_points: 3 })
    expect(payload.detect_points).toBe(3)
    expect(payload.window_seconds).toBe(86400)
    // 旧草稿 / 清空输入：按 0 兜底，不能把 undefined 发给后端
    const legacy = { ...base, detect_points: undefined } as unknown as JobFormValues
    expect(buildJobPayload(legacy).detect_points).toBe(0)
  })
})

describe('新建任务表单的即时校验', () => {
  it('窗口时长低于下限时会被当场钳到下限', async () => {
    renderJobForm()
    // delay: null —— AntD 的受控输入每次按键都要等一轮渲染，默认延迟会超时
    const user = userEvent.setup({ delay: null })

    const valueInput = screen.getByLabelText('窗口时长')
    await user.clear(valueInput)
    await user.type(valueInput, '0')
    await user.tab() // 失焦 → InputNumber 按 min 钳制

    await waitFor(() => expect(valueInput).toHaveValue('1'))
  })

  it('必填项没填时拦下提交，不等后端 400', async () => {
    const onSubmit = renderJobForm()
    const user = userEvent.setup({ delay: null })

    // AntD 的 Select 不是原生 <select>，只能点开下拉再选选项
    await user.click(screen.getByLabelText(/指标/))
    await user.click(await screen.findByTitle('demo-metric'))
    await user.type(screen.getByLabelText(/任务名称/), 'j')
    await user.click(screen.getByLabelText(/检测算法/))
    // 算法选项的 label 是 ReactNode（带「慢」「不可用」标记），没有 title 属性
    await user.click((await screen.findAllByText(/^iqr$/))[0])
    // AntD 给两个汉字的按钮自动插空格（"创 建"），用正则匹配
    await user.click(screen.getByRole('button', { name: /创\s*建/ }))

    await waitFor(() => {
      expect(screen.getByText('请输入执行间隔')).toBeInTheDocument()
    })
    expect(onSubmit).not.toHaveBeenCalled()
  }, 30000)
})
