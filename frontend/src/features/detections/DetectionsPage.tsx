import { List, Space, Tag } from 'antd'
import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { DetectionChart } from './DetectionChart'
import { badcaseLabel } from './detectionChart'
import { useDetectionDetail } from './queries'
import { useSummary } from '../evaluation/queries'
import type { Badcase, EvaluationRow } from '../../api/types'

/**
 * 检测记录页。
 *
 * 左栏序列列表（从 summary 的 rows 取），右栏检测详情图。
 *
 * ⚠️ 「该序列还没有检测结果」是**业务态**（`no_result`）——
 *    走 StateBoundary 的 bizState 路径显示空态，不是红色错误框。
 */
export function DetectionsPage() {
  const [params, setParams] = useSearchParams()
  const summary = useSummary()
  // 序列 ID 直接取自 URL —— 不另存一份 state，否则从评估页跳进来时状态不同步
  const seriesId = params.get('series_id') ?? undefined
  const detail = useDetectionDetail(seriesId)
  const listRef = useRef<HTMLDivElement>(null)

  /**
   * 把左栏滚动到选中的序列。
   *
   * ⚠️ 从评估报告点进来时，选中的序列可能在列表很靠后的位置 ——
   *    列表停在顶部的话，用户根本看不到自己选的是哪条。
   */
  useEffect(() => {
    if (!seriesId || !listRef.current) return
    const active = listRef.current.querySelector('.is-active')
    active?.scrollIntoView({ block: 'center' })
  }, [seriesId, summary.data])

  const select = (id: string) => {
    setParams({ series_id: id })
  }

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">检测记录</h1>
        <p className="page__subtitle">
          每条序列一次检测的完整结果：数值、分数、阈值，以及与真值比对出的误报、漏报区间。
        </p>
      </header>

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
            {(data) => (
              <List
                size="small"
                dataSource={data.rows as EvaluationRow[]}
                renderItem={(row) => (
                  <List.Item
                    className={row.series_id === seriesId ? 'is-active' : undefined}
                    onClick={() => select(row.series_id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <span className="mono">{row.series_id}</span>
                  </List.Item>
                )}
              />
            )}
          </StateBoundary>
        </aside>

        <div className="badcases-layout__detail">
          <StateBoundary
            isLoading={detail.isPending}
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
        </div>
      </div>
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
