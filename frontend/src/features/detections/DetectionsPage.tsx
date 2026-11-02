import { useEffect, useMemo, useRef, useState } from 'react'
import { Space, Tag } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtMetric } from '../../lib/format'
import { DetectionChart } from './DetectionChart'
import { badcaseLabel } from './detectionChart'
import { DetectionsList } from './DetectionsList'
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
  const summary = useSummary()
  const [filters, setFilters] = useState<EvaluationFilters>({})
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const listRef = useRef<HTMLDivElement>(null)

  // 选中项直接取自 URL —— 不另存一份 state，否则从评估页跳进来时状态不同步
  const seriesId = params.get('series_id') ?? undefined
  const detectorParam = params.get('detector') ?? undefined

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
    setParams({ series_id: row.series_id, detector: row.detector })
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">检测记录</h1>
        <p className="page__subtitle">
          每条序列一次检测的完整结果：数值、分数、阈值，以及与真值比对出的误报、漏报区间。
        </p>
      </header>

      <div className="filter-bar">
        <FilterBar rows={rows} filters={filters} onChange={setFilters} />
      </div>

      <div className="detections__meta muted">
        筛选后 {filtered.length} / {rows.length} 条记录
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
          {/* ⚠️ **没选中就自己画空态** —— 详情查询是「禁用」的，
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
      <Space wrap size="small">
        <span className="mono">{selected.series_id}</span>
        {selected.detector ? <Tag>{selected.detector}</Tag> : null}
        {row ? <Tag color="blue">{metricClassLabel(row.metric_class)}</Tag> : null}
        {row ? (
          <span className="muted">
            Precision <span className="mono">{fmtMetric(row.precision)}</span>
            · Recall <span className="mono">{fmtMetric(row.recall)}</span>
            · F1 <span className="mono">{fmtMetric(row.f1)}</span>
          </span>
        ) : null}
      </Space>
      {filteredOut ? (
        <p className="muted detections-detail__note">这条记录不在当前筛选结果里。</p>
      ) : null}
    </div>
  )
}

/** 检测偏差明细列表：类型 + 分组 + 原因。 */
function BadcaseList({ badcases }: { badcases: Badcase[] }) {
  if (!badcases.length) {
    return <p className="muted">这条序列没有检测偏差 —— 检测结果与真值一致。</p>
  }
  return (
    <ul className="badcase-list">
      {badcases.map((item, index) => (
        <li key={index}>
          <Space size="small" wrap>
            <Tag color={item.kind === 'false_positive' ? 'warning' : 'error'}>
              {badcaseLabel(item.kind)}
            </Tag>
            <span className="mono muted">{item.group}</span>
            <span className="muted">
              {item.indices.length} 点（{item.indices[0]} ~ {item.indices[item.indices.length - 1]}）
            </span>
          </Space>
          <p className="badcase-list__reason">{item.reason}</p>
        </li>
      ))}
    </ul>
  )
}
