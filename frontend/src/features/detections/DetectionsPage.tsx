import { useEffect, useMemo, useRef, useState } from 'react'
import { Table, Tabs } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useSearchParams } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtMetric } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import { DetectionChart } from './DetectionChart'
import { badcaseLabel } from './detectionChart'
import { DetectionsList } from './DetectionsList'
import { PlatformDetections } from './PlatformDetections'
import { useDetectionDetail } from './queries'
import { indexOfRow, isSelectedRow, resolveSelected, type RecordKey } from './records'
import { FilterBar } from '../evaluation/FilterBar'
import { filterRows, type EvaluationFilters } from '../evaluation/filters'
import { useSummary } from '../evaluation/queries'
import { metricClassLabel } from '../jobs/ClassificationCard'
import type { Badcase, EvaluationRow } from '../../api/types'

/** 每页多少条记录。 */
export const PAGE_SIZE = 20

/**
 * 检测记录页。
 *
 * 左栏记录索引（可筛选、可分页），右栏检测详情图。
 *
 * ⚠️ 一条记录是 **序列 × 算法** —— 同一序列在不同算法下是两条记录，
 *    列表项与高亮都必须带上算法，否则会串。
 *
 * ⚠️ 「该序列还没有检测结果」是**业务态**（`no_result`）——
 *    走 StateBoundary 的 bizState 路径显示空态，不是红色错误框。
 */
export function DetectionsPage() {
  const [params, setParams] = useSearchParams()
  // 从评估报告点进来会带 series_id —— 那是离线记录的深链接，不能落在平台页签上
  const view =
    params.get('view') === 'offline' || params.get('series_id')
      ? 'offline'
      : 'platform'

  const changeView = (key: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('view', key)
      // 切到平台页签时清掉离线记录的选中项 —— 否则上面那条判断会一直把它拉回离线
      if (key === 'platform') {
        next.delete('series_id')
        next.delete('detector')
      }
      return next
    })
  }

  return (
    <div className="page">
      <header className="titlebar">
        <h1>检测记录</h1>
      </header>
      <Tabs
        activeKey={view}
        onChange={changeView}
        items={[
          { key: 'platform', label: '平台运行' },
          { key: 'offline', label: '离线评测集' },
        ]}
      />
      {view === 'platform' ? <PlatformDetections /> : <OfflineDetections />}
    </div>
  )
}

/**
 * 离线评测集的检测记录（`reports/latest`）。
 *
 * ⚠️ 与「平台运行」是两套数据：这里是**算法在合成集上的逐条表现**，
 *    有真值、能算 P/R/F1；那边是任务实际跑出来的结果，没有真值。
 */
function OfflineDetections() {
  const [params, setParams] = useSearchParams()
  const summary = useSummary()
  const [filters, setFilters] = useState<EvaluationFilters>({})
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const listRef = useRef<HTMLDivElement>(null)

  // 选中项直接取自 URL —— 不另存一份 state，否则从评估页跳进来时状态不同步
  const seriesId = params.get('series_id') ?? undefined
  const detectorParam = params.get('detector') ?? undefined

  /** 把选中项写进 URL —— **合并**而不是覆盖，否则会把 `view` 一起冲掉。 */
  const selectParams = (next: { series_id: string; detector: string }) =>
    setParams((prev) => {
      const merged = new URLSearchParams(prev)
      merged.set('series_id', next.series_id)
      merged.set('detector', next.detector)
      return merged
    })

  const rows = useMemo(() => summary.data?.rows ?? [], [summary.data])
  const filtered = useMemo(() => filterRows(rows, filters), [rows, filters])
  const selected = useMemo(
    () => resolveSelected(rows, seriesId, detectorParam),
    [rows, seriesId, detectorParam],
  )
  const detail = useDetectionDetail(selected?.series_id, selected?.detector)

  /** 选中记录在报告里的那一行（拿形态与评估指标）。 */
  const selectedRow = useMemo(
    () => (selected ? rows.find((row) => isSelectedRow(row, selected)) : undefined),
    [rows, selected],
  )
  /** 选中记录被当前筛选排除掉了？ */
  const filteredOut = selected !== undefined && indexOfRow(filtered, selected) < 0

  /**
   * 当前页该显示哪一页。
   *
   * ⚠️ **两种情况都要处理**：
   *    1. 筛选后选中项不见了 → 回到第 1 页（否则停在越界页上，空列表）；
   *    2. 深链接指向第 3 页的记录 → 拨到它所在的那页，
   *       否则用户看不到自己选中的东西被高亮。
   */
  useEffect(() => {
    const index = indexOfRow(filtered, selected)
    if (index < 0) {
      setPage(1)
      return
    }
    const target = Math.floor(index / pageSize) + 1
    setPage((prev) => (prev === target ? prev : target))
  }, [selected, filtered, pageSize])

  /**
   * 默认选中第一条记录。
   *
   * ⚠️ 不选的话右栏是空的 —— 第一屏就只剩一个空框。
   *    选中项写在 URL 里，深链接与「从评估页点进来」都能对上。
   */
  useEffect(() => {
    if (seriesId || filtered.length === 0) return
    const first = filtered[0]
    selectParams({ series_id: first.series_id, detector: first.detector })
  }, [seriesId, filtered])

  /**
   * 把左栏滚动到选中的记录。
   *
   * ⚠️ 从评估报告点进来时，选中的序列可能在列表很靠后的位置 ——
   *    列表停在顶部的话，用户根本看不到自己选的是哪条。
   */
  useEffect(() => {
    if (!selected || !listRef.current) return
    const active = listRef.current.querySelector('.is-active')
    active?.scrollIntoView({ block: 'center' })
  }, [selected, filtered])

  const select = (row: EvaluationRow) => {
    selectParams({ series_id: row.series_id, detector: row.detector })
  }

  return (
    <div className="offline-detections">
      <div className="filter-bar">
        <FilterBar rows={rows} filters={filters} onChange={setFilters} />
        {/* 记录总数 —— 筛选之后才知道还剩几条 */}
        {rows.length > 0 ? (
          <span className="filter-bar__count mono dim">
            共 {rows.length} 条记录
            {filtered.length !== rows.length ? ` · 筛选后 ${filtered.length} 条` : ''}
          </span>
        ) : null}
      </div>

      <div className="badcases-layout">
        <aside className="badcases-layout__list" ref={listRef}>
          <StateBoundary
            isLoading={summary.isPending}
            error={summary.error}
            data={summary.data}
            isEmpty={(data) => data.rows.length === 0}
            emptyTitle="暂无报告"
            emptyHint="先运行 evaluate"
          >
            {() => (
              <DetectionsList
                rows={filtered}
                selected={selected}
                onSelect={select}
                page={page}
                pageSize={pageSize}
                onPageChange={(nextPage, nextSize) => {
                  setPage(nextPage)
                  setPageSize(nextSize)
                }}
              />
            )}
          </StateBoundary>
        </aside>

        <div className="badcases-layout__detail">
          {selected ? (
            <DetectionDetailHead
              selected={selected}
              row={selectedRow}
              filteredOut={filteredOut}
            />
          ) : null}
          {/* ⚠️ **没选中就自己画空态** —— 详情查询是「禁用」的， taste-skill-ignore
              `StateBoundary` 拿到 `data === undefined` 会返回 null，
              什么都不显示（连提示都没有）。 */}
          {selected === undefined ? (
            <div className="empty-state">
              <p className="empty-state__title">选一条序列</p>
              <p className="muted">从左边列表里选一条</p>
            </div>
          ) : (
            <StateBoundary
              // ⚠️ **不能用 `isPending`** —— react-query v5 里「被禁用」的查询
              //    仍然是 pending，没选中记录时右栏会永远显示骨架屏，
              //    而不是「选一条序列」的空态。`fetchStatus` 才是「真的在取」。
              isLoading={detail.fetchStatus !== 'idle'}
              error={detail.error}
              data={detail.data}
              bizTitles={{ no_result: '该序列还没有检测结果' }}
              emptyTitle="选一条序列"
              emptyHint="从左边列表里选一条"
            >
              {(data) => (
                <div className="badcase-detail">
                  <DetectionChart data={data} />
                  <BadcaseList badcases={data.badcases} />
                </div>
              )}
            </StateBoundary>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * 详情头：这条记录是谁。
 *
 * ⚠️ 有了筛选，列表与详情可能对不上 —— 头里说清「我在看哪条」才不让人猜。
 *
 * ⚠️ 用表格而不是一排标签 —— 这些是**键值事实**，对齐了才比得准。
 */
function DetectionDetailHead({
  selected,
  row,
  filteredOut,
}: {
  selected: RecordKey
  row: EvaluationRow | undefined
  filteredOut: boolean
}) {
  return (
    <div className="detections-detail__head">
      <table className="kvtable">
        <tbody>
          <tr>
            <th>序列</th>
            <td className="mono">{selected.series_id}</td>
            <th>算法</th>
            <td>{detectorLabel(selected.detector)}</td>
          </tr>
          <tr>
            <th>形态</th>
            <td>{row ? metricClassLabel(row.metric_class) : '—'}</td>
            <th>阈值</th>
            <td className="mono">{row ? fmtMetric(row.threshold) : '—'}</td>
          </tr>
          <tr>
            <th>Precision</th>
            <td className="mono">{row ? fmtMetric(row.precision) : '—'}</td>
            <th>Recall</th>
            <td className="mono">{row ? fmtMetric(row.recall) : '—'}</td>
          </tr>
          <tr>
            <th>F1</th>
            <td className="mono">{row ? fmtMetric(row.f1) : '—'}</td>
            <th>Range-F1</th>
            <td className="mono">{row ? fmtMetric(row.range_f1) : '—'}</td>
          </tr>
        </tbody>
      </table>
      {filteredOut ? (
        <p className="muted detections-detail__note">这条记录不在当前筛选结果里。</p>
      ) : null}
    </div>
  )
}

/** 检测偏差明细：类型 + 分组 + 原因。 */
function BadcaseList({ badcases }: { badcases: Badcase[] }) {
  const columns: ColumnsType<Badcase> = [
    {
      title: '类型',
      dataIndex: 'kind',
      key: 'kind',
      width: 90,
      render: (value: string) => (
        <span className={`pill ${value === 'false_positive' ? 'pill--p1' : 'pill--p0'}`}>
          {badcaseLabel(value)}
        </span>
      ),
    },
    {
      title: '分组',
      dataIndex: 'group',
      key: 'group',
      width: 160,
      render: (value: string) => <span className="mono dim">{value}</span>,
    },
    {
      title: '点区间',
      key: 'range',
      width: 190,
      render: (_value, row) => (
        <span className="mono">
          {row.indices.length} 点（{row.indices[0]} ~ {row.indices[row.indices.length - 1]}）
        </span>
      ),
    },
    {
      title: '原因',
      dataIndex: 'reason',
      key: 'reason',
      render: (value: string) => <span className="dim">{value}</span>,
    },
  ]

  if (!badcases.length) {
    return <p className="muted">这条序列没有检测偏差 —— 检测结果与真值一致。</p>
  }

  return (
    <Table<Badcase>
      rowKey={(_row, index) => String(index)}
      columns={columns}
      dataSource={badcases}
      size="small"
      pagination={false}
      scroll={{ x: 'max-content' }}
    />
  )
}
