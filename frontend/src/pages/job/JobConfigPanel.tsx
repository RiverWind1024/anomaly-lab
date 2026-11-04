import { Alert, Button, Form, Input, InputNumber, Select, Space } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertRulesEditor } from '../../features/jobs/AlertRulesEditor'
import { detectorLabel } from '../../lib/detectorLabels'
import { useUpdateJob } from '../../features/jobs/queries'
import { INTERVAL_SECONDS_MIN, WINDOW_POINTS_MAX, WINDOW_POINTS_MIN } from '../../features/jobs/limits'
import type { AlertRule, CatalogDetector, CatalogJob, CatalogMetric } from '../../api/types'

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
  window_points: number
  interval_seconds: number
  enabled: boolean
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
        window_points: job.window_points,
        interval_seconds: job.interval_seconds,
        enabled: job.enabled,
      })
      setRules(job.alert_rules ?? null)
    }
  }, [enabled, job, form])

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
      window_points: values.window_points,
      interval_seconds: values.interval_seconds,
      enabled: values.enabled,
      // ⚠️ 规则表**有值才传** —— 传 null 会被后端当成「显式置空」。
      alert_rules: rules && rules.length > 0 ? rules : undefined,
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
          label="检测指标"
          rules={[{ required: true, message: '请选择指标' }]}
          extra="换了指标，历史运行记录仍然保留，但之后的结果按新指标计算。"
        >
          <Select options={metricOptions} placeholder="选择指标" showSearch optionFilterProp="label" />
        </Form.Item>

        <Form.Item
          name="detector"
          label="检测算法"
          rules={[{ required: true, message: '请选择检测算法' }]}
          extra="「自动推荐」由形态分类器挑算法，每次运行可能选到不同的算法。"
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

        {/* ⚠️ wrap：窄屏上这两项要能换行 —— 挤在一行会顶出屏幕右边 taste-skill-ignore */}
        <Space size="large" wrap style={{ display: 'flex' }}>
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
            extra={`每次运行取最近 ${WINDOW_POINTS_MIN} ~ ${WINDOW_POINTS_MAX} 个点`}
          >
            <InputNumber
              min={WINDOW_POINTS_MIN}
              max={WINDOW_POINTS_MAX}
              step={100}
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
            extra={`定时任务的执行周期，最少 ${INTERVAL_SECONDS_MIN} 秒`}
          >
            <InputNumber min={INTERVAL_SECONDS_MIN} step={60} style={{ width: 180 }} />
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
