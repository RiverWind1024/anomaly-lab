import { Button, Form, Input, Modal, Space } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createSource, updateSource } from '../../api/platform'
import { catalogKey } from '../jobs/queries'
import type { CatalogSource } from '../../api/types'

export interface SourceFormValues {
  name: string
  path: string
  kind: string
}

/**
 * 数据源表单 —— 新增与编辑共用。
 *
 * ⚠️ 后端 `SourceIn` 只有三个字段：name / path / kind（默认 sqlite）。
 *
 * 编辑时**提交全量字段**（后端只改传了的，但全量更简单也更不容易出错）。
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

  const save = useMutation({
    mutationFn: (payload: { name: string; path: string; kind: string }) =>
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
    const values = await form.validateFields()
    save.mutate({
      name: values.name.trim(),
      path: values.path.trim(),
      kind: values.kind,
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
        initialValues={
          editing
            ? { name: editing.name, path: editing.path, kind: editing.kind }
            : { kind: 'sqlite' }
        }
      >
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="local" />
        </Form.Item>
        <Form.Item
          name="path"
          label="路径"
          rules={[{ required: true, message: '请输入路径' }]}
          extra="相对数据目录，或绝对路径。"
        >
          <Input placeholder="platform/source.db" spellCheck={false} />
        </Form.Item>
        <Form.Item name="kind" label="类型">
          <Input placeholder="sqlite" spellCheck={false} />
        </Form.Item>
      </Form>
    </Modal>
  )
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
