import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Table } from 'antd'
import { querySource } from '../../api/platform'
import type { CatalogMetric, CatalogSource } from '../../api/types'

/**
 * 浏览数据 —— 在数据源上跑一段**只读**查询，看几行原始数据。
 *
 * ⚠️ 查询由指标的 SQL 推导：去掉时间条件、加上 LIMIT。
 *    推导不出来就不查（不猜、不编）。
 */
export function buildBrowseSql(metric: CatalogMetric, limit = 8): string | null {
  let sql = metric.query.replace(/;\s*$/, '').trim()
  if (!sql) return null

  if (/\$timefilter/i.test(sql)) {
    sql = sql.replace(/\bAND\s+\$timefilter\b/i, '')
    sql = sql.replace(/\bWHERE\s+\$timefilter\b/i, '')
    sql = sql.replace(/\bWHERE\s+(?=AND\b)/i, '')
    sql = sql.replace(/\bAND\s+(?=\bORDER\b|\bGROUP\b|\bLIMIT\b)/i, '')
    // ⚠️ 还带着 $timefilter 就说明形式不认 —— 不硬猜
    if (/\$timefilter/i.test(sql)) return null
  }

  sql = sql.replace(/\bLIMIT\s+\d+\s*$/i, '').trim()
  return `${sql} LIMIT ${limit}`
}

/** 浏览数据面板。 */
export function SourceBrowse({
  source,
  metric,
}: {
  source: CatalogSource
  metric: CatalogMetric
}) {
  const sql = useMemo(() => buildBrowseSql(metric, 8), [metric])

  const browse = useQuery({
    queryKey: ['source-browse', source.id, sql],
    queryFn: () =>
      querySource(source.id, {
        sql: sql as string,
        limit: 8,
        time_column: metric.time_column,
        time_format: metric.time_format,
        source_timezone: metric.source_timezone,
      }),
    enabled: sql != null,
    retry: false,
  })

  if (!sql) return null

  const result = browse.data
  const columns = result?.columns ?? []

  return (
    <section className="panel" aria-labelledby="browseTitle">
      <div className="panel__head">
        <div>
          <h2 className="panel__title" id="browseTitle">
            浏览数据
          </h2>
          <p className="panel__meta mono">
            {browse.isPending
              ? '查询中…'
              : browse.isError
                ? '查询失败'
                : `${columns.length} 列 · ${result?.rows.length ?? 0} 行`}
          </p>
        </div>
        <span className="link">只读查询，不落库</span>
      </div>

      <code className="browse__sql mono">{sql}</code>

      {browse.isError ? (
        <p className="muted">这段查询跑不通 —— 到数据源详情页改一下指标的 SQL。</p>
      ) : (
        <Table
          rowKey={(_row, index) => String(index)}
          columns={columns.map((col, index) => ({
            title: <span className="mono">{col.name}</span>,
            dataIndex: String(index),
            key: col.name,
            align: index === 0 ? ('left' as const) : ('right' as const),
            render: (value: unknown) => (
              <span className="mono dim">
                {value === null || value === undefined
                  ? '—'
                  : typeof value === 'number'
                    ? value.toFixed(3)
                    : String(value)}
              </span>
            ),
          }))}
          dataSource={(result?.rows ?? []).map((row) => row as unknown[])}
          size="small"
          pagination={false}
          scroll={{ x: 'max-content' }}
        />
      )}
    </section>
  )
}
