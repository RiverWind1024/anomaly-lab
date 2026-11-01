import { useEffect, useMemo } from 'react'
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
  initialValues,
  onCancel,
  onSuccess,
}: {
  open: boolean
  sources: CatalogSource[]
  /** 传了就是编辑模式；不传是新增。 */
  editing?: CatalogMetric | null
  /** 新增时的默认数据源（在数据源详情页新增指标时用）。 */
  defaultSourceId?: number
  /** 外部预填（从数据浏览器的结果建指标时用）。 */
  initialValues?: Partial<MetricFormValues>
  onCancel: () => void
  onSuccess?: () => void
}) {
  const [form] = Form.useForm<MetricFormValues>()
  const qc = useQueryClient()
  const isEditing = Boolean(editing)

  /** 表单初值 —— 编辑态与外部预填合并。 */
  const initialFormValues = useMemo<Partial<MetricFormValues>>(
    () =>
      editing
        ? { ...editingToValues(editing), ...initialValues }
        : {
            source_id: defaultSourceId,
            // ⚠️ 名字与分组列也要给默认值 —— setFieldsValue 不会清掉
            //    store 里上一次编辑留下的值
            name: '',
            group_column: '',
            time_column: 'ts',
            value_column: 'value',
            time_format: 'iso_utc',
            source_timezone: 'UTC',
            missing_policy: 'drop',
            freq: '5min',
            query: DEFAULT_METRIC_QUERY,
            ...initialValues,
          },
    [editing, defaultSourceId, initialValues],
  )

  // ⚠️ antd 的 `initialValues` **只在挂载时生效一次** —— 先开「新增」再开「编辑」，
  //    或者浏览结果预填后再打开编辑，antd 都不会重新应用。
  //    这里显式把新值灌回表单。
  //    ⚠️ 只在弹窗打开时同步 —— 关闭时 Form 已被销毁（destroyOnClose），
  //    这时 setFieldsValue 会触发 antd 的「form 没挂上」警告。
  useEffect(() => {
    if (!open) return
    form.setFieldsValue(initialFormValues)
  }, [form, initialFormValues, open])

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
        initialValues={initialFormValues}
      >
        <MetricFormFields sources={sources} />
      </Form>
    </Modal>
  )
}

/** 编辑态 → 表单初值。 */
function editingToValues(editing: CatalogMetric): MetricFormValues {
  return {
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
}
