import { Form, Modal } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createMetric, updateMetric } from '../../api/platform'
import { catalogKey } from '../jobs/queries'
import {
  DEFAULT_METRIC_QUERY,
  MISSING_POLICY_OPTIONS,
  MetricFormFields,
  TIME_FORMAT_OPTIONS,
  buildMetricPayload,
  type MetricFormValues,
} from './MetricFormFields'
import type { CatalogMetric, CatalogSource } from '../../api/types'

export {
  DEFAULT_METRIC_QUERY,
  MISSING_POLICY_OPTIONS,
  TIME_FORMAT_OPTIONS,
  type MetricFormValues,
}

/**
 * 指标表单 —— 新增与编辑共用。
 *
 * 字段照搬旧 `platform.html` 的全部字段，一个都不能少。
 */
export function MetricForm({
  open,
  sources,
  editing,
  defaultSourceId,
  onCancel,
  onSuccess,
}: {
  open: boolean
  sources: CatalogSource[]
  /** 传了就是编辑模式；不传是新增。 */
  editing?: CatalogMetric | null
  /** 新增时的默认数据源（在数据源详情页新增指标时用）。 */
  defaultSourceId?: number
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
    save.mutate(buildMetricPayload(values))
  }

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
                source_id: defaultSourceId,
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
        <MetricFormFields sources={sources} />
      </Form>
    </Modal>
  )
}
