/** 归档检测记录：选一个归档数据集，确认后复制一份到归档目录。 */
import { useEffect, useState } from 'react'
import { Alert, Input, Modal, Select, Space, Tag, message } from 'antd'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { archiveDetection, listArchiveSets } from '../../api/archives'
import type { DetectionRecord } from '../../api/types'
import { detectorLabel } from '../../lib/detectorLabels'

export interface ArchivePickerModalProps {
  /** 要归档的记录；null = 弹窗关闭。 */
  record: DetectionRecord | null
  onClose: () => void
}

export function ArchivePickerModal({ record, onClose }: ArchivePickerModalProps) {
  const [setId, setSetId] = useState<number | undefined>(undefined)
  const [description, setDescription] = useState('')
  const queryClient = useQueryClient()

  const sets = useQuery({
    queryKey: ['archive-sets'],
    queryFn: listArchiveSets,
    enabled: record !== null,
  })

  // 每次打开都从空白开始 —— 避免上一次选的数据集残留
  useEffect(() => {
    if (record) {
      setSetId(undefined)
      setDescription('')
    }
  }, [record])

  const archive = useMutation({
    mutationFn: () => {
      if (setId === undefined || record === null) {
        throw new Error('请选择归档数据集')
      }
      return archiveDetection(setId, {
        run_id: record.run_id,
        series_id: record.series_id,
        description: description.trim(),
      })
    },
    onSuccess: () => {
      message.success('已归档')
      void queryClient.invalidateQueries({ queryKey: ['archive-sets'] })
      onClose()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '归档失败')
    },
  })

  const options = (sets.data?.sets ?? []).map((item) => ({
    value: item.id,
    label: `${item.name}（${item.n_records} 条）`,
  }))

  return (
    <Modal
      open={record !== null}
      title="归档检测记录"
      onCancel={onClose}
      onOk={() => archive.mutate()}
      okText="归档"
      cancelText="取消"
      confirmLoading={archive.isPending}
      okButtonProps={{ disabled: setId === undefined || sets.data?.sets.length === 0 }}
      destroyOnClose
    >
      {record ? (
        <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
          <div>
            <Space size="small" wrap>
              <Tag className="mono">{record.series_id}</Tag>
              <Tag>{detectorLabel(record.detector)}</Tag>
              <span className="muted mono">
                {record.job_name} · 运行 #{record.run_id}
              </span>
            </Space>
          </div>
          <Select
            aria-label="归档数据集"
            placeholder="选择归档数据集"
            style={{ width: '100%' }}
            value={setId}
            onChange={(value) => setSetId(value as number)}
            options={options}
            loading={sets.isPending}
          />
          <Input.TextArea
            aria-label="归档原因"
            placeholder="归档原因（可选）：例如此刻的误报值得复盘"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            maxLength={200}
            showCount
          />
          {sets.data?.sets.length === 0 ? (
            <Alert
              type="info"
              showIcon
              message={
                <>
                  还没有归档数据集，先到 <Link to="/archives">归档</Link> 页面创建一个。
                </>
              }
            />
          ) : null}
        </Space>
      ) : null}
    </Modal>
  )
}
