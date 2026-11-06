import { useMemo, useState } from 'react'
import { Card, Drawer, Select, Space, Switch, Table, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import { getDetectionRecords } from '../../api/platform'
import { getRunSeriesDetail } from '../../api/series'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtFullDateTime, fmtMetric } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import { DecisionTraceTimeline } from '../evaluation/DecisionTraceTimeline'
import { metricClassLabel } from '../jobs/ClassificationCard'
import { PreviewChart } from '../jobs/PreviewChart'
import { ScaleStatusTags } from '../jobs/ScaleStatusTags'
import type { DetectionRecord, RunSeriesDetail } from '../../api/types'
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

/** 空数组 → null：`PreviewChart` 用「有没有带」决定画不画带。 */
function bandOf(values: number[] | undefined): (number | null)[] | null {
  return values && values.length > 0 ? values : null
}

/**
 * 尺度结论的一格展示。
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
        title: '',
        key: 'open',
        width: 96,
        // ⚠️ 固定在右侧 —— 列多时必须横向滚动，否则「查看流程」被推出屏幕，
        //    用户根本不知道点行能打开决策链。
        fixed: 'right',
        render: (_value, row) => (
          <span className="mono dim">{row.has_decision ? '查看流程 →' : '查看 →'}</span>
        ),
      },
    ],
    [],
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
    </div>
  )
}

/**
 * 单条平台检测记录：波形 + 决策链。
 *
 * ⚠️ 决策链放在**波形上方** —— 用户点进来最想知道的不是「长什么样」，
 *    而是「这次为什么这么判」。图是佐证，流程是结论。
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
      {(data: RunSeriesDetail) => (
        <div className="platform-record">
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2 className="panel__title">检测流程</h2>
                <p className="panel__meta">
                  数据质量 → 能力探测 → 形态判断 → 算法选择 → 阈值与分级 → 结果
                </p>
              </div>
              <Space size="small" wrap>
                <ScaleStatusTags
                  status={data.status}
                  scaleSource={data.scale_source}
                  scaleFallback={data.scale_fallback}
                />
              </Space>
            </div>
            <DecisionTraceTimeline trace={data.decision ?? {}} />
          </section>

          <Card size="small" title="波形与分数" className="platform-record__chart">
            <PreviewChart
              timestamps={data.timestamps}
              values={data.values}
              scores={data.scores}
              baseline={bandOf(data.baseline)}
              lower={bandOf(data.lower)}
              upper={bandOf(data.upper)}
              severity={data.severity}
              alertThreshold={data.alert_threshold ?? 0}
              criticalThreshold={data.critical_threshold ?? 0}
              levels={data.levels ?? ['正常']}
            />
          </Card>

          <table className="kvtable">
            <tbody>
              <tr>
                <th>检测器</th>
                <td>{detectorLabel(data.detector)}</td>
                <th>点数</th>
                <td className="mono">{data.values.length}</td>
              </tr>
              <tr>
                <th>告警点</th>
                <td className="mono">{data.severity.filter((level) => level > 0).length}</td>
                <th>P0 点</th>
                <td className="mono">{data.severity.filter((level) => level >= 2).length}</td>
              </tr>
              <tr>
                <th>尺度</th>
                <td className="mono">{data.scale_source || '—'}</td>
                <th>阈值</th>
                <td className="mono">{fmtMetric(data.alert_threshold ?? 0)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </StateBoundary>
  )
}
