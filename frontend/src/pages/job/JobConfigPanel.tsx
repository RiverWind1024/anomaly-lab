import { Alert, Button, Form, Input, InputNumber, Select, Space } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { hint } from '../../components/FieldHint'
import { AlertRulesEditor } from '../../features/jobs/AlertRulesEditor'
import { AlgorithmGuide } from '../../features/jobs/AlgorithmGuide'
import { detectorLabel } from '../../lib/detectorLabels'
import { useUpdateJob } from '../../features/jobs/queries'
import {
  DETECT_POINTS_MIN,
  INTERVAL_SECONDS_MIN,
  WINDOW_UNIT_OPTIONS,
  WINDOW_UNIT_SECONDS,
  splitWindow,
  type WindowUnit,
} from '../../features/jobs/limits'
import type { AlertRule, CatalogDetector, CatalogJob, CatalogMetric } from '../../api/types'
import { directionHint, directionOptions, normalizeDirection } from '../../lib/alertDirection'

export interface JobConfigPanelProps {
  job: CatalogJob
  metrics: CatalogMetric[]
  detectors: CatalogDetector[]
  /** 任务不存在时为 false —— 此时一个请求都不该发。 */
  enabled: boolean
}

interface ConfigFormValues {
  name: string
  metric_id: number
  detector: string
  window_value: number
  window_unit: WindowUnit
  interval_seconds: number
  /** 只对窗口最后 N 个点判定告警；0 = 检测整个窗口。 */
  detect_points: number
  enabled: boolean
  alert_direction: 'both' | 'above' | 'below'
}

/**
 * 任务配置面板 —— 详情页的**主体**。
 *
 * 之前这个页面把运行记录、预览图、多算法对比、分类结论、反馈历史
 * 全堆在一起，什么都看不清楚。现在配置归配置，其余各自独立成页。
 *
 * ⚠️ 告警规则**可以编辑**了（之前是只读）——
 *    阈值（2.5 / 3.75 那些）恰恰是最常调的东西，
 *    把它锁在「新建任务时」是锁错了地方。
 */
export function JobConfigPanel({ job, metrics, detectors, enabled }: JobConfigPanelProps) {
  const [form] = Form.useForm<ConfigFormValues>()
  const update = useUpdateJob(job.id)

  /**
   * 告警规则 —— 单独 state，不走 Form。
   *
   * ⚠️ 它是个**结构化**的值（档位表 + 附加条件），
   *    塞进 Form 会让「表单值 ↔ 编辑器值」多一层转换，没有好处。
   */
  const [rules, setRules] = useState<AlertRule[] | null>(null)

  // 换任务时要重填表单（同一组件实例会被路由复用）
  useEffect(() => {
    if (enabled) {
      form.setFieldsValue({
        name: job.name,
        metric_id: job.metric_id,
        detector: job.detector,
        ...splitWindow(job.window_seconds),
        interval_seconds: job.interval_seconds,
        detect_points: job.detect_points ?? 0,
        enabled: job.enabled,
        alert_direction: job.alert_direction,
      })
      setRules(job.alert_rules ?? null)
    }
  }, [enabled, job, form])

  /** 当前选中的算法支持哪一侧 —— 没基线只能报偏高。 */
  const selectedDetectorName = Form.useWatch('detector', form)
  const selectedDetector = useMemo(
    () => detectors.find((d) => d.name === selectedDetectorName),
    [detectors, selectedDetectorName],
  )
  const detectorDirection = selectedDetector?.direction ?? 'both'

  useEffect(() => {
    const current = form.getFieldValue('alert_direction')
    const next = normalizeDirection(current, detectorDirection)
    if (next !== current) form.setFieldValue('alert_direction', next)
  }, [detectorDirection, form])

  const metricOptions = useMemo(
    () => metrics.map((m) => ({ value: m.id, label: m.name })),
    [metrics],
  )

  const detectorOptions = useMemo(
    () =>
      detectors.map((d) => ({
        value: d.name,
        // ⚠️ 用统一的中文标签表 —— 后端给的 label 只覆盖主名，
        //    而任务配置里可能存着**旧名**（改名前建的）。
        //    顺带显示**惯用阈值** —— 每个算法的最佳工作点不一样，
        //    用户换算法时要知道该把阈值调成多少。
        label: `${detectorLabel(d.name)}（惯用 ${d.default_threshold}）`,
        disabled: d.available === false,
        title: d.available === false ? (d.reason ?? '当前环境不可用') : undefined,
      })),
    [detectors],
  )

  /**
   * 换了算法 → 分数量纲可能变了。
   *
   * ⚠️ 统计型的分数是「几个尺度单位」（阈值 2.5 / 3.5），
   *    Chronos 的分数是 [0,1] 的相对越界程度（阈值 0.5）。
   *    跨族沿用旧阈值 = **告警永远不触发**，而界面显示「一切正常」。
   *
   * ⚠️ 后端会**自动把阈值换成新算法的默认值** ——
   *    这里提前告诉用户，免得保存后阈值「莫名其妙变了」。
   */
  const scoreFamily = useCallback(
    (name: string) =>
      name === 'chronos' || detectors.find((d) => d.name === name)?.score_type === 'prob'
        ? 'prob'
        : 'scale',
    [detectors],
  )

  const [familyHint, setFamilyHint] = useState<string | null>(null)

  const handleDetectorChange = (name: string) => {
    if (scoreFamily(name) !== scoreFamily(job.detector)) {
      const target = detectors.find((d) => d.name === name)
      setFamilyHint(
        `「${name}」的分数量纲与当前算法不同（${
          target?.score_type === 'prob' ? '0~1 的相对越界程度' : '偏离基线的倍数'
        }），保存后告警阈值会自动换成 ${target?.default_threshold ?? '该算法的默认值'}。`,
      )
    } else {
      setFamilyHint(null)
    }
  }

  const handleSave = async () => {
    let values: ConfigFormValues
    try {
      values = await form.validateFields()
    } catch {
      // 校验没过：错误已经显示在对应表单项上
      return
    }
    update.mutate({
      name: values.name.trim(),
      metric_id: values.metric_id,
      detector: values.detector,
      window_seconds: values.window_value * WINDOW_UNIT_SECONDS[values.window_unit],
      interval_seconds: values.interval_seconds,
      detect_points: values.detect_points ?? 0,
      enabled: values.enabled,
      // ⚠️ 规则表**有值才传** —— 传 null 会被后端当成「显式置空」。
      alert_rules: rules && rules.length > 0 ? rules : undefined,
      alert_direction: values.alert_direction ?? 'both',
    })
  }

  return (
    <div className="job-config">
      {update.error instanceof Error && (
        <Alert type="error" showIcon message={update.error.message} style={{ marginBottom: 16 }} />
      )}
      {update.isSuccess && !update.isPending && (
        <Alert type="success" showIcon message="配置已保存" style={{ marginBottom: 16 }} />
      )}

      <Form form={form} layout="vertical" requiredMark="optional" disabled={!enabled}>
        <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
          <Input placeholder="例：web-api 延迟巡检" />
        </Form.Item>

        <Form.Item
          name="metric_id"
          label={hint('检测指标', '换了指标，历史运行记录仍然保留，但之后的结果按新指标计算。')}
          rules={[{ required: true, message: '请选择指标' }]}
        >
          <Select options={metricOptions} placeholder="选择指标" showSearch optionFilterProp="label" />
        </Form.Item>

        <Form.Item
          name="detector"
          label={
            <span className="field-hint">
              检测算法
              <AlgorithmGuide guide={selectedDetector?.guide} />
            </span>
          }
          rules={[{ required: true, message: '请选择检测算法' }]}
        >
          <Select
            options={detectorOptions}
            placeholder="选择算法"
            onChange={handleDetectorChange}
          />
        </Form.Item>

        {familyHint ? (
          <Alert type="info" showIcon message={familyHint} style={{ marginBottom: 16 }} />
        ) : null}

        <Form.Item
          name="alert_direction"
          label="告警方向"
          extra={directionHint(detectorDirection)}
        >
          <Select options={directionOptions(detectorDirection)} />
        </Form.Item>

        {/* ⚠️ wrap：窄屏上这两项要能换行 —— 挤在一行会顶出屏幕右边 taste-skill-ignore */}
        <Space size="large" wrap style={{ display: 'flex' }}>
          <Form.Item label="时间窗口" required>
            <Space.Compact>
              <Form.Item
                name="window_value"
                noStyle
                rules={[
                  { required: true, message: '请输入窗口时长' },
                  { type: 'number', min: 1, message: '至少为 1' },
                ]}
              >
                <InputNumber
                  aria-label="窗口时长"
                  min={1}
                  step={1}
                  placeholder="1"
                  style={{ width: 120 }}
                />
              </Form.Item>
              <Form.Item name="window_unit" noStyle>
                <Select aria-label="窗口单位" options={WINDOW_UNIT_OPTIONS} style={{ width: 96 }} />
              </Form.Item>
            </Space.Compact>
          </Form.Item>
          <Form.Item
            name="detect_points"
            label={hint(
              '检测点数',
              '0 = 检测整个窗口。填 N 则只对最近 N 个点判定告警，更早的点只用于统计基线。',
            )}
            rules={[
              {
                validator: (_, value) => {
                  if (value === undefined || value === null) return Promise.resolve()
                  if (value < DETECT_POINTS_MIN) {
                    return Promise.reject(new Error('检测点数不能为负数'))
                  }
                  return Promise.resolve()
                },
              },
            ]}
          >
            <InputNumber min={DETECT_POINTS_MIN} step={1} style={{ width: 180 }} />
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

        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Select
            options={[
              { value: true, label: '启用（按间隔定时执行）' },
              { value: false, label: '停用（不再定时执行）' },
            ]}
          />
        </Form.Item>

        <Form.Item label="告警规则">
          <AlertRulesEditor
            value={rules}
            onChange={setRules}
            defaultThreshold={job.alert_threshold}
            defaultCriticalThreshold={job.critical_threshold}
            disabled={!enabled}
          />
        </Form.Item>

        <Button type="primary" loading={update.isPending} onClick={handleSave}>
          保存配置
        </Button>
      </Form>
    </div>
  )
}
