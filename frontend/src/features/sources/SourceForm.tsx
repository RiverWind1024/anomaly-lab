import { useMemo } from 'react'
import { Button, Form, Input, Modal, Select, Space } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createSource, updateSource } from '../../api/platform'
import { catalogKey } from '../jobs/queries'
import type { CatalogSource, SourceConfig } from '../../api/types'

/**
 * 表单里的 HTTP 配置。
 *
 * ⚠️ headers/body 是 **JSON 文本** —— textarea 编辑的是文本，
 *    提交前才 JSON.parse 成对象（解析失败要报错，不能静默吞掉）。
 */
export interface SourceFormConfig extends Omit<SourceConfig, 'headers' | 'body'> {
  headers?: string
  body?: string
}

export interface SourceFormValues {
  name: string
  path: string
  kind: string
  /** HTTP 源的配置 —— sqlite 源不用（提交时传 `{}`）。 */
  config?: SourceFormConfig
}

/** 数据源类型 —— 后端只认 sqlite / http，别的会 400。 */
const KIND_OPTIONS = [
  { value: 'sqlite', label: 'SQLite 文件' },
  { value: 'http', label: 'HTTP SQL 网关' },
]

const METHOD_OPTIONS = [
  { value: 'GET', label: 'GET' },
  { value: 'POST', label: 'POST' },
]

const FORMAT_OPTIONS = [
  { value: 'json', label: 'json' },
  { value: 'csv', label: 'csv' },
  { value: 'jsonl', label: 'jsonl' },
]

/** 对象 → JSON 文本（给 textarea）。空对象当空文本。 */
function toJsonText(value: Record<string, unknown> | undefined): string {
  if (!value || Object.keys(value).length === 0) return ''
  return JSON.stringify(value, null, 2)
}

/**
 * JSON 文本 → 对象的校验器。
 *
 * ⚠️ 空文本算「没填」，不报错 —— body 本来就是可空的。
 * ⚠️ 解析失败**必须报错** —— 静默吞掉等于把用户的配置丢掉。
 */
function jsonObjectValidator(label: string) {
  return (_rule: unknown, value?: string) => {
    const text = (value ?? '').trim()
    if (!text) return Promise.resolve()
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      return Promise.reject(new Error(`${label}不是合法的 JSON`))
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return Promise.reject(new Error(`${label}必须是 JSON 对象`))
    }
    return Promise.resolve()
  }
}

/**
 * 数据源表单 —— 新增与编辑共用。
 *
 * ⚠️ **config 是「整体替换」语义**（后端 `_merge_config`）：
 *    提交时必须带上**完整**的 config —— 少传一个顶层键，它就没了。
 *    所以这里的每个字段都要带上去，没填的也带默认值。
 * ⚠️ **headers 的值前端看到的是脱敏值**（`••••` / `Bearer ••••`）——
 *    原样回传，后端会把它还原成真值；前端**不要**过滤 `••••`。
 */
export function SourceForm({
  open,
  editing,
  onCancel,
  onSuccess,
}: {
  open: boolean
  /** 传了就是编辑模式；不传是新增。 */
  editing?: CatalogSource | null
  onCancel: () => void
  onSuccess?: () => void
}) {
  const [form] = Form.useForm<SourceFormValues>()
  const qc = useQueryClient()
  const isEditing = Boolean(editing)

  // ⚠️ useWatch 首次渲染返回 undefined —— 用 initialValues 的值兜底，
  //    否则弹窗刚打开时会闪一下「类型未知」。
  const kind = Form.useWatch('kind', form) ?? editing?.kind ?? 'sqlite'

  const initialValues = useMemo<SourceFormValues>(
    () => {
      const cfg = editing?.config ?? {}
      return {
        name: editing?.name ?? '',
        path: editing?.path ?? '',
        kind: editing?.kind ?? 'sqlite',
        config: {
          url: cfg.url ?? '',
          method: cfg.method ?? 'GET',
          format: cfg.format ?? 'json',
          headers: toJsonText(cfg.headers),
          body: toJsonText(cfg.body),
          rows_path: cfg.rows_path ?? '',
        },
      }
    },
    [editing],
  )

  const save = useMutation({
    mutationFn: (payload: {
      name: string
      path: string
      kind: string
      config: SourceConfig
    }) =>
      isEditing && editing
        ? updateSource(editing.id, payload)
        : createSource(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: catalogKey })
      form.resetFields()
      onCancel()
      onSuccess?.()
    },
  })

  const handleOk = async () => {
    let values: SourceFormValues
    try {
      values = await form.validateFields()
    } catch {
      // 校验没过：错误已经显示在对应表单项上。
      // ⚠️ 必须 catch —— 否则 validateFields 抛出的 promise 没人接。
      return
    }
    const isHttp = values.kind === 'http'
    save.mutate({
      name: values.name.trim(),
      // http 源没有「路径」这回事 —— 后端对它做 strip()，空串即可。
      path: isHttp ? '' : values.path.trim(),
      kind: values.kind,
      config: isHttp ? buildHttpConfig(values, editing) : {},
    })
  }

  return (
    <Modal
      open={open}
      title={isEditing ? '编辑数据源' : '新增数据源'}
      onCancel={onCancel}
      onOk={handleOk}
      okText={isEditing ? '保存' : '新增'}
      cancelText="取消"
      confirmLoading={save.isPending}
      destroyOnClose
      width={560}
    >
      {save.error instanceof Error && <p className="form-error">{save.error.message}</p>}
      <Form
        form={form}
        layout="vertical"
        requiredMark="optional"
        initialValues={initialValues}
      >
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="local" />
        </Form.Item>

        <Form.Item
          name="kind"
          label="类型"
          rules={[{ required: true, message: '请选择类型' }]}
          extra="HTTP SQL 网关：把 SQL 透传给远端（如 ClickHouse HTTP 接口）。"
        >
          <Select options={KIND_OPTIONS} />
        </Form.Item>

        {kind === 'http' ? (
          <>
            <Form.Item
              name={['config', 'url']}
              label="URL"
              rules={[{ required: true, message: '请输入 URL' }]}
              extra="请求 URL 模板，{sql} 是 SQL 占位符。例：https://ch:8123/?query={sql}"
            >
              <Input placeholder="https://ch:8123/?query={sql}" spellCheck={false} />
            </Form.Item>

            <Form.Item name={['config', 'method']} label="方法">
              <Select options={METHOD_OPTIONS} />
            </Form.Item>

            <Form.Item name={['config', 'format']} label="响应格式">
              <Select options={FORMAT_OPTIONS} />
            </Form.Item>

            <Form.Item
              name={['config', 'headers']}
              label="请求头"
              rules={[{ validator: jsonObjectValidator('请求头') }]}
              extra="JSON 对象。值会是脱敏的，原样提交即可保留真值。"
            >
              <Input.TextArea rows={3} spellCheck={false} placeholder='{"X-Token": "••••"}' />
            </Form.Item>

            <Form.Item
              name={['config', 'body']}
              label="请求体"
              rules={[{ validator: jsonObjectValidator('请求体') }]}
              extra="JSON 对象，可空。POST 时作为请求体发出。"
            >
              <Input.TextArea rows={3} spellCheck={false} placeholder='{"query": "{sql}"}' />
            </Form.Item>

            <Form.Item
              name={['config', 'rows_path']}
              label="行数组路径"
              extra="JSON 响应是对象时，从里面取数组的点号路径。例：data.items"
            >
              <Input placeholder="data.items" spellCheck={false} />
            </Form.Item>
          </>
        ) : (
          <Form.Item
            name="path"
            label="路径"
            rules={[{ required: true, message: '请输入路径' }]}
            extra="相对数据目录，或绝对路径。"
          >
            <Input placeholder="platform/source.db" spellCheck={false} />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}

/**
 * 表单值 → HTTP 源的 config。
 *
 * ⚠️ **必须带上全部字段** —— 后端是「整体替换」，少传一个键它就没了。
 * ⚠️ headers/body 的值**原样回传**（可能是脱敏值）—— 后端会还原真值。
 */
function buildHttpConfig(
  values: SourceFormValues,
  editing: CatalogSource | null | undefined,
): SourceConfig {
  const cfg = values.config ?? {}
  const config: SourceConfig = {
    url: (cfg.url ?? '').trim(),
    method: cfg.method ?? 'GET',
    format: cfg.format ?? 'json',
    headers: parseJsonObject(cfg.headers) as Record<string, string>,
    body: parseJsonObject(cfg.body),
    rows_path: (cfg.rows_path ?? '').trim(),
  }
  // ⚠️ 超时没有表单字段 —— 保留原值，别被「整体替换」静默改成默认值。
  const timeout = editing?.config?.timeout_seconds
  if (timeout !== undefined) config.timeout_seconds = timeout
  return config
}

/** JSON 文本 → 对象。空文本 → 空对象（校验器已经保证能解析）。 */
function parseJsonObject(text: string | undefined): Record<string, unknown> {
  const trimmed = (text ?? '').trim()
  if (!trimmed) return {}
  return JSON.parse(trimmed) as Record<string, unknown>
}

/** 页面工具条上的「新增数据源」按钮（弹窗由页面持有）。 */
export function SourceCreateButton({ onClick }: { onClick: () => void }) {
  return (
    <Space>
      <Button type="primary" onClick={onClick}>
        新增数据源
      </Button>
    </Space>
  )
}
