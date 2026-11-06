import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Alert, Form, Input, InputNumber, Modal, Select, Space } from 'antd'
import type { AlertDirection, AlertRule, CatalogDetector, CatalogMetric } from '../../api/types'
import { AlertRulesEditor } from './AlertRulesEditor'
import { directionHint, directionOptions, normalizeDirection } from '../../lib/alertDirection'
import { detectorLabel } from '../../lib/detectorLabels'
import { INTERVAL_SECONDS_MIN, WINDOW_POINTS_MAX, WINDOW_POINTS_MIN } from './limits'
import { defaultRuleList } from './rules'

export interface JobFormValues {
  metric_id: number
  name: string
  detector: string
  window_points: number
  interval_seconds: number
  alert_rules: AlertRule[] | null
  alert_direction: AlertDirection
}

/**
 * 表单回填值 —— 从实验记录跳转过来时带过来的草稿。
 *
 * ⚠️ `alert_rules` 单独放 —— 规则表由 `AlertRulesEditor` 持有，
 *    不走 Form 的字段绑定。
 * ⚠️ `alert_direction` 可省略 —— 旧草稿没有这个字段，表单按「双向」兜底。
 */
export type JobFormInitialValues = Omit<
  JobFormValues,
  'alert_rules' | 'alert_direction'
> & {
  alert_rules?: AlertRule[] | null
  alert_direction?: AlertDirection
}

export interface JobFormProps {
  open: boolean
  metrics: CatalogMetric[]
  detectors: CatalogDetector[]
  onCancel: () => void
  onSubmit: (values: JobFormValues) => void
  submitting?: boolean
  error?: string
  /** 打开时回填的值 —— 一键建任务时从实验记录带过来。 */
  initialValues?: JobFormInitialValues
  /** 表单顶部的说明 —— 从实验记录来时 telling 用户「这些值是怎么选出来的」。 */
  note?: ReactNode
}

/**
 * 新建告警任务表单。
 *
 * 这里是 spec §8.2-A 里最容易漏的几条旧功能的落点：
 *   - 倍数条件 + 绝对值条件两种规则写法
 *   - 倍数必须为正（前端当场拦，不等 422）
 *   - 规则语义说明文案
 *   - **选算法时按 default_threshold 自动预填默认规则**
 */
export function JobForm({
  open,
  metrics,
  detectors,
  onCancel,
  onSubmit,
  submitting = false,
  error,
  initialValues,
  note,
}: JobFormProps) {
  const [form] = Form.useForm<JobFormValues>()
  const [rules, setRules] = useState<AlertRule[] | null>(null)

  // ⚠️ 草稿用 ref 拿着 —— `initialValues` 每次渲染都是新对象，
  //    直接进依赖数组会让 effect 每次都重置表单，用户打的字就没了。
  const draftRef = useRef(initialValues)
  draftRef.current = initialValues

  // 打开时重置上一次的输入；有草稿就回填。
  useEffect(() => {
    if (!open) return
    form.resetFields()
    const draft = draftRef.current
    if (draft) {
      const { alert_rules: draftRules, ...fields } = draft
      form.setFieldsValue(fields)
      setRules(draftRules ?? null)
    } else {
      setRules(null)
    }
  }, [open, form])

  const detectorOptions = useMemo(
    () =>
      detectors.map((d) => ({
        value: d.name,
        label: (
          <span>
            {/* ⚠️ 用统一的中文标签表 —— 后端给的 label 只覆盖主名 */}
            {detectorLabel(d.name)}
            {/* ⚠️ **显示惯用阈值** ——
                每个算法的「最佳工作点」不一样（iqr 2.5 / mad 3.5 /
                theil_sen 3.5），用户换算法时要知道该把阈值调成多少。
                不显示的话，用户只能靠猜 —— 而猜错就是误报率翻倍。 */}
            <span className="muted"> （惯用 {d.default_threshold}）</span>
            {d.available === false && (
              <span className="muted"> （不可用）</span>
            )}
            {d.slow && d.available !== false && (
              <span className="muted"> （慢）</span>
            )}
          </span>
        ),
        // 不可用就不让选 —— 后端也会拒绝创建任务
        disabled: d.available === false,
        // title 悬停说明：不可用时给原因，慢时给量级
        title:
          d.available === false
            ? (d.reason ?? '当前环境不可用')
            : d.slow
              ? '慢：约 2 秒/序列，定时任务请留足执行间隔'
              : undefined,
      })),
    [detectors],
  )

  const metricOptions = useMemo(
    () => metrics.map((m) => ({ value: m.id, label: m.name })),
    [metrics],
  )

  /** 当前选中的算法 —— 决定告警规则的默认档位。 */
  const selectedDetectorName = Form.useWatch('detector', form)
  const selectedDetector = useMemo(
    () => detectors.find((d) => d.name === selectedDetectorName),
    [detectors, selectedDetectorName],
  )
  /** 算法支持的方向 —— 没有基线（如 event_count）只能报偏高。 */
  const detectorDirection = selectedDetector?.direction ?? 'both'

  /**
   * 切到不支持「只报偏低」的算法时，把已经选中的 below 改回 both。
   *
   * ⚠️ 否则提交的是一个**必然不生效**的配置：用户以为在只报偏低，
   *    实际一条都不会报（后端会标 direction_applied=false）。
   */
  useEffect(() => {
    const current = form.getFieldValue('alert_direction')
    const next = normalizeDirection(current, detectorDirection)
    if (next !== current) form.setFieldValue('alert_direction', next)
  }, [detectorDirection, form])

  /**
   * 选算法 → 自动预填默认规则。
   *
   * ⚠️ 预填的是**结构化的档位表**（P1 × base、P0 × base×1.5），
   *    不是文本 —— 用户能直接看到并改这两个数。
   */
  const onDetectorChange = (name: string) => {
    const det = detectors.find((d) => d.name === name)
    if (!det) return
    setRules(defaultRuleList(det.default_threshold))
  }

  const handleOk = async () => {
    let values: JobFormValues
    try {
      values = await form.validateFields()
    } catch {
      // 校验没过：错误已经显示在对应表单项上，这里不再重复提示。
      // ⚠️ 必须 catch —— 否则 validateFields 抛出的 promise 没人接，
      //    浏览器控制台会出现 unhandled rejection。
      return
    }
    onSubmit({ ...values, alert_rules: rules })
  }

  return (
    <Modal
      open={open}
      title="新建告警任务"
      onCancel={onCancel}
      onOk={handleOk}
      okText="创建"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={640}
    >
      {note && (
        <Alert type="info" showIcon message={note} style={{ marginBottom: 16 }} />
      )}
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      <Form form={form} layout="vertical" requiredMark="optional">
        <Form.Item
          name="metric_id"
          label="指标"
          rules={[{ required: true, message: '请选择指标' }]}
        >
          <Select options={metricOptions} placeholder="选择指标" showSearch optionFilterProp="label" />
        </Form.Item>

        <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
          <Input placeholder="例：web-api 延迟巡检" />
        </Form.Item>

        <Form.Item
          name="detector"
          label="检测算法"
          rules={[{ required: true, message: '请选择检测算法' }]}
        >
          <Select options={detectorOptions} onChange={onDetectorChange} placeholder="选择算法" />
        </Form.Item>

        <Form.Item
          name="alert_direction"
          label="告警方向"
          initialValue="both"
          extra={directionHint(detectorDirection)}
        >
          <Select options={directionOptions(detectorDirection)} />
        </Form.Item>

        <Space size="large" style={{ display: 'flex' }}>
          <Form.Item
            name="window_points"
            label="窗口点数"
            rules={[
              { required: true, message: '请输入窗口点数' },
              {
                type: 'number',
                min: WINDOW_POINTS_MIN,
                max: WINDOW_POINTS_MAX,
                message: `窗口点数需在 ${WINDOW_POINTS_MIN} ~ ${WINDOW_POINTS_MAX} 之间`,
              },
            ]}
          >
            <InputNumber
              min={WINDOW_POINTS_MIN}
              max={WINDOW_POINTS_MAX}
              step={100}
              placeholder="500"
              style={{ width: 180 }}
            />
          </Form.Item>
          <Form.Item
            name="interval_seconds"
            label="执行间隔（秒）"
            rules={[
              { required: true, message: '请输入执行间隔' },
              {
                type: 'number',
                min: INTERVAL_SECONDS_MIN,
                message: `执行间隔至少 ${INTERVAL_SECONDS_MIN} 秒`,
              },
            ]}
          >
            <InputNumber min={INTERVAL_SECONDS_MIN} step={60} placeholder="300" style={{ width: 180 }} />
          </Form.Item>
        </Space>

        <Form.Item label="告警规则">
          <AlertRulesEditor
            value={rules}
            onChange={setRules}
            defaultThreshold={selectedDetector?.default_threshold ?? 2.5}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 供 JobForm 之外的场景使用：把解析结果转成提交载荷。 */
export function buildJobPayload(values: JobFormValues) {
  return {
    metric_id: values.metric_id,
    name: values.name,
    detector: values.detector,
    window_points: values.window_points,
    interval_seconds: values.interval_seconds,
    alert_rules: values.alert_rules,
    // ⚠️ 兜底 both —— 旧草稿 / 旧表单值可能没有这个字段。
    alert_direction: values.alert_direction ?? 'both',
  }
}
