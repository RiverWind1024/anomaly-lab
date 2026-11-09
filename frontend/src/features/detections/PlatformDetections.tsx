import { useMemo, useState } from 'react'
import { Button, Drawer, Popconfirm, Select, Space, Switch, Table, Tag, Tooltip, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMutation, useQuery } from '@tanstack/react-query'
import { deleteDetection, getDetectionRecords } from '../../api/platform'
import { getRunSeriesDetail } from '../../api/series'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtFullDateTime } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import { metricClassLabel } from '../jobs/ClassificationCard'
import { ScaleStatusTags } from '../jobs/ScaleStatusTags'
import type { DetectionRecord, RunSeriesDetail } from '../../api/types'
import { ArchivePickerModal } from './ArchivePickerModal'
import { SeriesRecordDetail } from './SeriesRecordDetail'
import './platformDetections.css'

const PAGE_SIZE = 20

/** 平台运行产生的检测记录清单。 */
function useDetectionRecords(opts: {
  jobId?: number
  onlyAlerts: boolean
  page: number
}) {
  return useQuery({
    queryKey: ['detection-records', opts.jobId ?? 'all', opts.onlyAlerts, opts.page],
    queryFn: () =>
      getDetectionRecords({
        jobId: opts.jobId,
        onlyAlerts: opts.onlyAlerts,
        limit: PAGE_SIZE,
        offset: (opts.page - 1) * PAGE_SIZE,
      }),
  })
}

/** 某次运行里一条序列的完整时序（含决策链）。 */
function usePlatformSeriesDetail(runId: number, seriesId: string) {
  return useQuery({
    queryKey: ['platform-series-detail', runId, seriesId],
    queryFn: () => getRunSeriesDetail(runId, seriesId),
  })
}

/** 尺度结论的一格展示。
 *
 * ⚠️ 「无法判定」和「尺度降级」是两个不同的坏消息，颜色分开：
 *    前者是「什么都没算出来」，后者是「换了一档尺度才算出来」。
 */
function ScaleCell({ record }: { record: DetectionRecord }) {
  if (!record.sufficient) return <span className="muted">—</span>
  return (
    <Space size={4} wrap>
      <span className="mono dim">{record.scale_source || '—'}</span>
      <ScaleStatusTags
        status={record.status}
        scaleSource={record.scale_source}
        scaleFallback={record.scale_fallback}
      />
    </Space>
  )
}

export function PlatformDetections() {
  const [jobId, setJobId] = useState<number | undefined>(undefined)
  const [onlyAlerts, setOnlyAlerts] = useState(false)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<DetectionRecord | undefined>(undefined)

  const records = useDetectionRecords({ jobId, onlyAlerts, page })
  const data = records.data
  const [archiving, setArchiving] = useState<DetectionRecord | null>(null)

  const remove = useMutation({
    mutationFn: (row: DetectionRecord) => deleteDetection(row.run_id, row.series_id),
    onSuccess: (_result, row) => {
      message.success('已删除')
      if (selected?.run_id === row.run_id && selected?.series_id === row.series_id) {
        setSelected(undefined)
      }
      void records.refetch()
    },
    onError: (err) => {
      message.error(err instanceof Error ? err.message : '删除失败')
    },
  })

  const columns: ColumnsType<DetectionRecord> = useMemo(
    () => [
      {
        title: '运行',
        dataIndex: 'run_id',
        key: 'run_id',
        width: 86,
        render: (value: number) => <span className="mono">#{value}</span>,
      },
      {
        title: '开始时间',
        dataIndex: 'started_at',
        key: 'started_at',
        width: 170,
        render: (value: string) => <span className="mono dim nowrap">{fmtFullDateTime(value)}</span>,
      },
      {
        title: '任务 / 指标',
        key: 'job',
        render: (_value, row) => (
          <div className="stacked">
            <span>{row.job_name}</span>
            <span className="stacked__sub mono">{row.metric_name}</span>
          </div>
        ),
      },
      {
        title: '序列',
        dataIndex: 'series_id',
        key: 'series_id',
        render: (value: string, row) => (
          <div className="stacked">
            <span className="mono">{value}</span>
            {row.metric_class ? (
              <span className="stacked__sub">{metricClassLabel(row.metric_class)}</span>
            ) : null}
          </div>
        ),
      },
      {
        title: '算法',
        dataIndex: 'detector',
        key: 'detector',
        width: 170,
        render: (value: string, row) => (
          <Space size={4} wrap>
            <span>{detectorLabel(value)}</span>
            {row.fallback ? (
              <Tooltip title="形态推荐了别的算法，但这个算法不可用或不可靠，已回退">
                <Tag color="warning">回退</Tag>
              </Tooltip>
            ) : null}
          </Space>
        ),
      },
      {
        title: '告警',
        dataIndex: 'n_alerts',
        key: 'n_alerts',
        width: 112,
        align: 'right',
        render: (value: number, row) => (
          <span className="mono nowrap">
            {value}
            {row.n_p0 > 0 ? <span className="dim"> / P0 {row.n_p0}</span> : null}
          </span>
        ),
      },
      {
        title: '尺度',
        key: 'scale',
        width: 150,
        render: (_value, row) => <ScaleCell record={row} />,
      },
      {
        title: '操作',
        key: 'actions',
        width: 180,
        // ⚠️ 固定在右侧 —— 列多时必须横向滚动，否则操作按钮被推出屏幕。
        fixed: 'right',
        render: (_value, row) => (
          <Space size={0} onClick={(event) => event.stopPropagation()}>
            <Button size="small" type="link" onClick={() => setSelected(row)}>
              查看
            </Button>
            <Button size="small" type="link" onClick={() => setArchiving(row)}>
              归档
            </Button>
            <Popconfirm
              title="删除这条检测记录？"
              description="删除后不可恢复；已归档的副本不受影响。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => remove.mutate(row)}
            >
              <Button size="small" type="link" danger loading={remove.isPending}>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [remove],
  )

  return (
    <div className="platform-detections">
      <div className="filter-bar">
        <Space size="middle" wrap>
          <Select
            allowClear
            placeholder="全部任务"
            style={{ minWidth: 200 }}
            value={jobId}
            onChange={(value) => {
              setJobId(value as number | undefined)
              setPage(1)
            }}
            options={(data?.jobs ?? []).map((job) => ({
              value: job.id,
              label: job.name,
            }))}
          />
          <label
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
          >
            <Switch
              size="small"
              checked={onlyAlerts}
              onChange={(value) => {
                setOnlyAlerts(value)
                setPage(1)
              }}
            />
            只看有告警
          </label>
        </Space>
        <span className="filter-bar__count">
          共 <b className="num">{data?.total ?? 0}</b> 条检测记录
        </span>
      </div>

      <StateBoundary
        isLoading={records.isPending}
        error={records.error}
        data={data}
        isEmpty={(value) => (value?.records ?? []).length === 0}
        emptyTitle="还没有检测记录"
        emptyHint="在「告警任务」里运行一次，检测结果会出现在这里"
      >
        {() => (
          <Table<DetectionRecord>
            rowKey={(row) => `${row.run_id}-${row.series_id}`}
            columns={columns}
            dataSource={data?.records ?? []}
            size="small"
            scroll={{ x: 'max-content' }}
            onRow={(row) => ({
              onClick: () => setSelected(row),
              style: { cursor: 'pointer' },
            })}
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              total: data?.total ?? 0,
              showSizeChanger: false,
              onChange: setPage,
            }}
          />
        )}
      </StateBoundary>

      <Drawer
        open={selected !== undefined}
        onClose={() => setSelected(undefined)}
        width={1000}
        title={
          selected ? (
            <Space size="small" wrap>
              <span className="mono">{selected.series_id}</span>
              <Tag>{detectorLabel(selected.detector)}</Tag>
              <span className="muted mono">运行 #{selected.run_id}</span>
            </Space>
          ) : (
            '检测记录'
          )
        }
      >
        {selected ? (
          <PlatformRecordDetail runId={selected.run_id} seriesId={selected.series_id} />
        ) : null}
      </Drawer>

      <ArchivePickerModal record={archiving} onClose={() => setArchiving(null)} />
    </div>
  )
}
/**
 * 单条平台检测记录：查询 + 状态边界，内容交给共享的 SeriesRecordDetail。
 */
function PlatformRecordDetail({ runId, seriesId }: { runId: number; seriesId: string }) {
  const detail = usePlatformSeriesDetail(runId, seriesId)

  return (
    <StateBoundary
      isLoading={detail.isPending}
      error={detail.error}
      data={detail.data}
      emptyTitle="这条记录没有时序数据"
      emptyHint="产物文件可能已被清理（保留策略）"
    >
      {(data: RunSeriesDetail) => <SeriesRecordDetail data={data} />}
    </StateBoundary>
  )
}
