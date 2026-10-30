import { Button, Form, Input, Modal, Space } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createSource } from '../../api/platform'
import { catalogKey } from '../jobs/queries'

export interface SourceFormValues {
  name: string
  path: string
  kind: string
}

/**
 * 新增数据源表单。
 *
 * ⚠️ 后端 `SourceIn` 只有三个字段：name / path / kind（默认 sqlite）。
 */
export function SourceForm({
  open,
  onCancel,
  onSuccess,
}: {
  open: boolean
  onCancel: () => void
  onSuccess?: () => void
}) {
  const [form] = Form.useForm<SourceFormValues>()
  const qc = useQueryClient()

  const create = useMutation({
    mutationFn: (payload: Parameters<typeof createSource>[0]) => createSource(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: catalogKey })
      form.resetFields()
      onCancel()
      onSuccess?.()
    },
  })

  const handleOk = async () => {
    const values = await form.validateFields()
    create.mutate({
      name: values.name.trim(),
      path: values.path.trim(),
      kind: values.kind,
    })
  }

  return (
    <Modal
      open={open}
      title="新增数据源"
      onCancel={onCancel}
      onOk={handleOk}
      okText="新增"
      cancelText="取消"
      confirmLoading={create.isPending}
      destroyOnClose
      width={560}
    >
      {create.error instanceof Error && <p className="form-error">{create.error.message}</p>}
      <Form form={form} layout="vertical" requiredMark="optional">
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
        <Form.Item name="kind" label="类型" initialValue="sqlite">
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
