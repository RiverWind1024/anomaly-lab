import { Form, Input, Select } from 'antd'
import { hint } from '../../components/FieldHint'
import type { CatalogSource } from '../../api/types'
import { freqValidator } from './freq'

export interface MetricFormValues {
  source_id: number
  name: string
  query: string
  time_column: string
  value_column: string
  group_column?: string | null
  time_format: string
  source_timezone: string
  missing_policy: string
  freq: string
}

/** 时间格式的取值（后端 `TimeFormat`）。 */
export const TIME_FORMAT_OPTIONS = [
  { value: 'iso_utc', label: 'iso_utc（带时区或 UTC）' },
  { value: 'iso_naive', label: 'iso_naive（无时区墙钟）' },
  { value: 'epoch_s', label: 'epoch_s' },
  { value: 'epoch_ms', label: 'epoch_ms' },
]

/** 缺失值策略的取值（后端 `MissingPolicy`）。 */
export const MISSING_POLICY_OPTIONS = [
  { value: 'drop', label: 'drop（丢弃并计数）' },
  { value: 'interpolate', label: 'interpolate（线性插值）' },
  { value: 'error', label: 'error（直接失败）' },
]

/**
 * 查询语句的默认值。
 *
 * ⚠️ **`$timefilter` 是后端的占位符** —— 前端只原样提交，
 *    不要替换成实际的时间范围。
 */
export const DEFAULT_METRIC_QUERY = 'SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts'

export interface MetricFormFieldsProps {
  sources: CatalogSource[]
}

/**
 * 指标的字段集 —— 弹窗表单与指标详情页**共用**。
 *
 * 抽出来是为了让两处永远一致：字段少一个，新增时能填、编辑时就漏。
 */
export function MetricFormFields({ sources }: MetricFormFieldsProps) {
  const sourceOptions = sources.map((s) => ({ value: s.id, label: s.name }))

  return (
    <>
      <div className="metric-form__grid">
        <Form.Item
          name="source_id"
          label="数据源"
          rules={[{ required: true, message: '请选择数据源' }]}
        >
          <Select options={sourceOptions} placeholder="选择数据源" />
        </Form.Item>

        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="cpu" />
        </Form.Item>

        <Form.Item
          name="time_column"
          label="时间列"
          rules={[{ required: true, message: '请输入时间列' }]}
        >
          <Input placeholder="ts" spellCheck={false} />
        </Form.Item>

        <Form.Item
          name="value_column"
          label="值列"
          rules={[{ required: true, message: '请输入值列' }]}
        >
          <Input placeholder="value" spellCheck={false} />
        </Form.Item>

        {/* ⚠️ 「可选」由 antd 的 requiredMark 自动标 —— 别再手写一遍 */}
        <Form.Item name="group_column" label="分组列">
          <Input placeholder="host" spellCheck={false} />
        </Form.Item>

        <Form.Item
          name="freq"
          label="频率"
          rules={[
            { required: true, message: '请输入频率' },
            // 格式当场拦下，不等提交后的后端 400
            { validator: freqValidator },
          ]}
        >
          <Input placeholder="5min / 1h / 1d" spellCheck={false} />
        </Form.Item>

        <Form.Item name="time_format" label="时间格式">
          <Select options={TIME_FORMAT_OPTIONS} />
        </Form.Item>

        <Form.Item
          name="source_timezone"
          label="源时区"
          rules={[{ required: true, message: '请输入源时区' }]}
        >
          <Input placeholder="Asia/Shanghai" spellCheck={false} />
        </Form.Item>

        <Form.Item name="missing_policy" label="缺失值策略">
          <Select options={MISSING_POLICY_OPTIONS} />
        </Form.Item>
      </div>

      <Form.Item
        name="query"
        label={hint(
          '查询语句',
          '$timefilter 是后端的占位符 —— 原样提交，不要替换成实际时间范围。',
        )}
        rules={[{ required: true, message: '请输入查询语句' }]}
      >
        <Input.TextArea rows={3} spellCheck={false} />
      </Form.Item>
    </>
  )
}

/** 把表单值转成后端载荷（新增与编辑共用）。 */
export function buildMetricPayload(values: MetricFormValues) {
  const group = values.group_column?.trim()
  return {
    source_id: values.source_id,
    name: values.name.trim(),
    query: values.query,
    time_column: values.time_column.trim(),
    value_column: values.value_column.trim(),
    // 分组列可空 —— 留空就传 null，别传空串
    // （后端用 exclude_unset，null 表示**显式清空**）
    group_column: group ? group : null,
    time_format: values.time_format as 'iso_utc' | 'iso_naive' | 'epoch_s' | 'epoch_ms',
    source_timezone: values.source_timezone.trim() || 'UTC',
    missing_policy: values.missing_policy as 'drop' | 'interpolate' | 'error',
    freq: values.freq.trim(),
  }
}
