import { Form, Input, Modal, Select } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createMetric, updateMetric } from '../../api/platform'
import type { CatalogMetric, CatalogSource } from '../../api/types'
import { catalogKey } from '../jobs/queries'
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

/**
 * 指标表单 —— 新增与编辑共用。
 *
 * 字段照搬旧 `platform.html` 的全部字段，一个都不能少。
 */
export function MetricForm({
  open,
  sources,
  editing,
  onCancel,
  onSuccess,
}: {
  open: boolean
  sources: CatalogSource[]
  /** 传了就是编辑模式；不传是新增。 */
  editing?: CatalogMetric | null
  onCancel: () => void
  onSuccess?: () => void
}) {
  const [form] = Form.useForm<MetricFormValues>()
  const qc = useQueryClient()
  const isEditing = Boolean(editing)

  const save = useMutation({
    mutationFn: (payload: Parameters<typeof createMetric>[0]) =>
      isEditing && editing
        ? updateMetric(editing.id, payload)
        : createMetric(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: catalogKey })
      form.resetFields()
      onCancel()
      onSuccess?.()
    },
  })

  const handleOk = async () => {
    let values: MetricFormValues
    try {
      values = await form.validateFields()
    } catch {
      // 校验没过：错误已经显示在对应表单项上。
      // ⚠️ 必须 catch —— 否则 validateFields 抛出的 promise 没人接，
      //    浏览器控制台会出现 unhandled rejection。
      return
    }
    const group = values.group_column?.trim()
    save.mutate({
      source_id: values.source_id,
      name: values.name.trim(),
      query: values.query,
      time_column: values.time_column.trim(),
      value_column: values.value_column.trim(),
      // 分组列可空 —— 留空就传 null，别传空串
      // （后端用 exclude_unset，null 表示**显式清空**）
      group_column: group ? group : null,
      time_format: values.time_format as Parameters<typeof createMetric>[0]['time_format'],
      source_timezone: values.source_timezone.trim() || 'UTC',
      missing_policy: values.missing_policy as Parameters<typeof createMetric>[0]['missing_policy'],
      freq: values.freq.trim(),
    })
  }

  const sourceOptions = sources.map((s) => ({ value: s.id, label: s.name }))

  return (
    <Modal
      open={open}
      title={isEditing ? '编辑指标' : '新增指标'}
      onCancel={onCancel}
      onOk={handleOk}
      okText={isEditing ? '保存' : '新增'}
      cancelText="取消"
      confirmLoading={save.isPending}
      destroyOnClose
      width={760}
    >
      {save.error instanceof Error && <p className="form-error">{save.error.message}</p>}
      <Form
        form={form}
        layout="vertical"
        requiredMark="optional"
        initialValues={
          editing
            ? {
                source_id: editing.source_id,
                name: editing.name,
                query: editing.query,
                time_column: editing.time_column,
                value_column: editing.value_column,
                group_column: editing.group_column ?? '',
                time_format: editing.time_format,
                source_timezone: editing.source_timezone,
                missing_policy: editing.missing_policy,
                freq: editing.freq,
              }
            : {
                time_column: 'ts',
                value_column: 'value',
                time_format: 'iso_utc',
                source_timezone: 'UTC',
                missing_policy: 'drop',
                freq: '5min',
                query: DEFAULT_METRIC_QUERY,
              }
        }
      >
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

          <Form.Item name="group_column" label="分组列" extra="可空 —— 填了会按它拆成多条序列">
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
            extra="数字 + 单位，单位可选 s / min / m / h / d（如 5min、1h、1d）"
          >
            <Input placeholder="5min" spellCheck={false} />
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
          label="查询语句"
          rules={[{ required: true, message: '请输入查询语句' }]}
          extra={
            <>
              <code>$timefilter</code> 是后端的占位符 —— 原样提交，不要替换成实际时间范围。
            </>
          }
        >
          <Input.TextArea rows={3} spellCheck={false} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
