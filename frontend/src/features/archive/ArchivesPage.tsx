/** 归档页：归档数据集 + 数据集里的检测记录副本。 */
import { useState } from 'react'
import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createArchiveSet,
  deleteArchiveRecord,
  deleteArchiveSet,
  getArchiveRecordDetail,
  getArchiveSet,
  listArchiveSets,
} from '../../api/archives'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtFullDateTime } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import type { ArchiveRecord, ArchiveSet } from '../../api/types'
import { SeriesRecordDetail } from '../detections/SeriesRecordDetail'

interface CreateForm {
  name: string
  description?: string
}

export function ArchivesPage() {
  const [selectedId, setSelectedId] = useState<number | undefined>(undefined)
  const [viewing, setViewing] = useState<ArchiveRecord | null>(null)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm<CreateForm>()
  const queryClient = useQueryClient()

  const sets = useQuery({ queryKey: ['archive-sets'], queryFn: listArchiveSets })
  const detail = useQuery({
    queryKey: ['archive-set', selectedId],
    queryFn: () => getArchiveSet(selectedId as number),
    enabled: selectedId !== undefined,
  })
  const recordDetail = useQuery({
    queryKey: ['archive-record', viewing?.id],
    queryFn: () => getArchiveRecordDetail(viewing?.id as number),
    enabled: viewing !== null,
  })

  const create = useMutation({
    mutationFn: (values: CreateForm) =>
      createArchiveSet({ name: values.name.trim(), description: values.description ?? '' }),
    onSuccess: (created) => {
      message.success('归档数据集已创建')
      setCreating(false)
      form.resetFields()
      void queryClient.invalidateQueries({ queryKey: ['archive-sets'] })
      setSelectedId(created.id)
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '创建失败'),
  })

  const removeSet = useMutation({
    mutationFn: (setId: number) => deleteArchiveSet(setId),
    onSuccess: (_result, setId) => {
      message.success('归档数据集已删除')
      if (selectedId === setId) setSelectedId(undefined)
      void queryClient.invalidateQueries({ queryKey: ['archive-sets'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
  })

  const removeRecord = useMutation({
    mutationFn: (record: ArchiveRecord) =>
      deleteArchiveRecord(record.archive_set_id, record.id),
    onSuccess: () => {
      message.success('已移出归档')
      void queryClient.invalidateQueries({ queryKey: ['archive-set', selectedId] })
      void queryClient.invalidateQueries({ queryKey: ['archive-sets'] })
    },
    onError: (err) => message.error(err instanceof Error ? err.message : '移出失败'),
  })

  const columns: ColumnsType<ArchiveRecord> = [
    {
      title: '序列',
      dataIndex: 'series_id',
      key: 'series_id',
      render: (value: string, row) => (
        <div className="stacked">
          <span className="mono">{value}</span>
          <span className="stacked__sub">
            {row.job_name} · {row.metric_name}
          </span>
        </div>
      ),
    },
    {
      title: '算法',
      dataIndex: 'detector',
      key: 'detector',
      width: 150,
      render: (value: string) => detectorLabel(value),
    },
    {
      title: '告警',
      dataIndex: 'n_alerts',
      key: 'n_alerts',
      width: 110,
      align: 'right',
      render: (value: number, row) => (
        <span className="mono nowrap">
          {value}
          {row.n_p0 > 0 ? <span className="dim"> / P0 {row.n_p0}</span> : null}
        </span>
      ),
    },
    {
      title: '数据范围',
      key: 'range',
      width: 210,
      render: (_value, row) =>
        row.start_ts ? (
          <span className="mono dim nowrap">
            {fmtFullDateTime(row.start_ts)} → {fmtFullDateTime(row.end_ts)}
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      title: '说明',
      dataIndex: 'description',
      key: 'description',
      width: 220,
      render: (value: string) =>
        value ? (
          <span>{value}</span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      title: '归档时间',
      dataIndex: 'archived_at',
      key: 'archived_at',
      width: 170,
      render: (value: string) => (
        <span className="mono dim nowrap">{fmtFullDateTime(value)}</span>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      fixed: 'right',
      render: (_value, row) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => setViewing(row)}>
            查看
          </Button>
          <Popconfirm
            title="移出归档？"
            description="副本文件会一起删除；原检测记录不受影响。"
            okText="移出"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => removeRecord.mutate(row)}
          >
            <Button size="small" type="link" danger>
              移出
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="page">
      <header className="titlebar">
        <div className="titlebar__lead">
          <h1>归档</h1>
          <p className="finding muted">
            手动收藏的检测记录副本 —— 原记录被删除或清理后，这里仍可查看。
          </p>
        </div>
        <div className="titlebar__actions">
          <Button type="primary" onClick={() => setCreating(true)}>
            新建归档数据集
          </Button>
        </div>
      </header>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 320px) minmax(0, 1fr)',
          gap: 24,
          alignItems: 'start',
        }}
      >
        <section className="panel" aria-labelledby="archiveSetsTitle">
          <div className="panel__head">
            <div>
              <h2 className="panel__title" id="archiveSetsTitle">
                归档数据集
              </h2>
              <p className="panel__meta mono">{sets.data?.sets.length ?? 0} 个数据集</p>
            </div>
          </div>
          <StateBoundary
            isLoading={sets.isPending}
            error={sets.error}
            data={sets.data}
            isEmpty={(value) => value.sets.length === 0}
            emptyTitle="还没有归档数据集"
            emptyHint="先新建一个，再到「检测记录」把记录归档进来"
          >
            {(value) => (
              <List<ArchiveSet>
                size="small"
                dataSource={value.sets}
                renderItem={(item) => (
                  <List.Item
                    onClick={() => setSelectedId(item.id)}
                    style={{
                      cursor: 'pointer',
                      paddingInline: 12,
                      background:
                        selectedId === item.id ? 'var(--surface-raised)' : undefined,
                      borderRadius: 6,
                    }}
                    actions={[
                      <Popconfirm
                        key="delete"
                        title="删除整个归档数据集？"
                        description="其中的归档副本会一起删除，不可恢复。"
                        okText="删除"
                        okButtonProps={{ danger: true }}
                        cancelText="取消"
                        onConfirm={() => removeSet.mutate(item.id)}
                      >
                        <Button
                          size="small"
                          type="link"
                          danger
                          onClick={(event) => event.stopPropagation()}
                        >
                          删除
                        </Button>
                      </Popconfirm>,
                    ]}
                  >
                    <List.Item.Meta
                      title={item.name}
                      description={
                        <span className="muted">
                          {item.n_records} 条 · {fmtFullDateTime(item.created_at)}
                        </span>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </StateBoundary>
        </section>

        <section className="panel" aria-labelledby="archiveRecordsTitle">
          <div className="panel__head">
            <div>
              <h2 className="panel__title" id="archiveRecordsTitle">
                {detail.data?.set.name ?? '归档记录'}
              </h2>
              <p className="panel__meta">
                {detail.data?.set.description || '选择一个归档数据集查看记录'}
              </p>
            </div>
          </div>
          {selectedId === undefined ? (
            <Empty description="选择左侧的归档数据集" />
          ) : (
            <StateBoundary
              isLoading={detail.isPending}
              error={detail.error}
              data={detail.data}
              isEmpty={(value) => value.records.length === 0}
              emptyTitle="这个数据集还没有记录"
              emptyHint="到「检测记录」里点某条记录的「归档」按钮"
            >
              {(value) => (
                <Table<ArchiveRecord>
                  rowKey="id"
                  size="small"
                  columns={columns}
                  dataSource={value.records}
                  scroll={{ x: 'max-content' }}
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                />
              )}
            </StateBoundary>
          )}
        </section>
      </div>

      <Modal
        open={creating}
        title="新建归档数据集"
        okText="创建"
        cancelText="取消"
        confirmLoading={create.isPending}
        onCancel={() => {
          setCreating(false)
          form.resetFields()
        }}
        onOk={() => {
          void form.validateFields().then((values) => create.mutate(values))
        }}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="例：2026-11 误报复盘" maxLength={80} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={3} placeholder="可选：这批记录为什么值得保留" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        open={viewing !== null}
        onClose={() => setViewing(null)}
        width={1000}
        title={
          viewing ? (
            <Space size="small" wrap>
              <span className="mono">{viewing.series_id}</span>
              <Tag>{detectorLabel(viewing.detector)}</Tag>
              <span className="muted mono">运行 #{viewing.run_id}</span>
            </Space>
          ) : (
            '归档记录'
          )
        }
      >
        <StateBoundary
          isLoading={recordDetail.isPending}
          error={recordDetail.error}
          data={recordDetail.data}
          emptyTitle="归档副本缺失"
          emptyHint="文件可能被手工删除"
        >
          {(data) => <SeriesRecordDetail data={data} />}
        </StateBoundary>
      </Drawer>
    </div>
  )
}
