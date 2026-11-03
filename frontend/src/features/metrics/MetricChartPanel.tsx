/**
 * 指标的时序预览 —— **用指标的取数配置**跑一次，画出图与明细。
 *
 * ⚠️ 与「数据浏览器」的区别：
 *    - 浏览器是**写 SQL** 看任意结果（还没定指标）；
 *    - 这里是**看一个已保存（或正在编辑）的指标**长什么样。
 *
 * ⚠️ 时间范围由**后端**按 `freq` + `window_points` 算 ——
 *    与指标运行时同一段代码（`freq_delta`），所以「预览看到的」
 *    就是「告警任务真正会跑的那一段」。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Table, Typography } from 'antd'
import { querySource } from '../../api/platform'
import type { SourceQueryColumn } from '../../api/types'
import { BrowseChart } from '../sources/BrowseChart'
import type { ColumnRoles } from '../sources/roles'

export interface MetricChartConfig {
  /** 指标的 SQL（必须含恰好一个 `$timefilter`）。 */
  query: string
  time_column: string
  value_column: string
  group_column?: string | null
  time_format: string
  source_timezone: string
}

export interface MetricChartPanelProps {
  sourceId: number
  config: MetricChartConfig
  /** 取多少个点 —— 来自告警任务的「窗口点数」。 */
  windowPoints: number
  /** 采样频率 —— 与 window_points 一起决定窗口有多长。 */
  freq: string
  /** 配置变了就自动重跑（编辑页的草稿）。 */
  auto?: boolean
}

/** 明细列表的单页行数 —— 与数据浏览器一致。 */
const PAGE_SIZE = 20

export function MetricChartPanel({
  sourceId,
  config,
  windowPoints,
  freq,
  auto = false,
}: MetricChartPanelProps) {
  const [data, setData] = useState<{
    columns: SourceQueryColumn[]
    rows: unknown[][]
    timeValues: (number | null)[] | null
    total: number
    truncated: boolean
    elapsed: number
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  /**
   * 角色 —— 直接用指标的配置，**不猜**。
   *
   * ⚠️ 与指标运行时一致：时间列、值列、分组列都是指标自己声明的。
   */
  const roles: ColumnRoles = useMemo(
    () => ({
      time_column: config.time_column,
      value_column: config.value_column,
      group_column: config.group_column ?? undefined,
    }),
    [config.time_column, config.value_column, config.group_column],
  )

  /**
   * 取多少行。
   *
   * ⚠️ 窗口内是「每条序列 × window_points 个点」—— 分组数事先不知道
   *    （取决于数据本身），只能给个够用的余量。
   *    ⚠️ 余量给小了会**截断**：7 条序列 × 60 点 = 413 行，
   *    只给 400 就会看到「还有更多」而看不到全貌。
   */
  const limit = Math.min(5000, Math.max(500, windowPoints * 10 + 200))

  const run = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await querySource(sourceId, {
        sql: config.query,
        time_column: config.time_column,
        time_format: config.time_format,
        source_timezone: config.source_timezone,
        freq,
        window_points: windowPoints,
        limit,
      })
      setData({
        columns: result.columns,
        rows: result.rows,
        timeValues: result.time_values ?? null,
        total: result.total,
        truncated: result.truncated,
        elapsed: result.elapsed_ms,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  /**
   * 跑一次 —— 首次**立刻**跑，之后（`auto` 时）去抖重跑。
   *
   * ⚠️ 首次不跑的话，预览页打开是一片空白 ——
   *    让用户自己点「刷新」是多余的。
   */
  const firstRun = useRef(true)
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false
      void run()
      return
    }
    if (!auto) return
    // ⚠️ 去抖 500ms：逐字输入不该逐次发请求
    const timer = setTimeout(() => {
      void run()
    }, 500)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    auto,
    sourceId,
    config.query,
    config.time_column,
    config.time_format,
    config.source_timezone,
    freq,
    windowPoints,
  ])

  /** 明细表的列。 */
  const tableColumns = useMemo(
    () =>
      (data?.columns ?? []).map((column, index) => ({
        title: column.name,
        // ⚠️ 行是 `{key, cells}` 的包装 —— 用数组路径取到 cells 里的那一列
        dataIndex: ['cells', index] as (string | number)[],
        key: column.name,
        render: (value: unknown) =>
          value === null || value === undefined ? (
            <span className="muted">—</span>
          ) : (
            String(value)
          ),
      })),
    [data?.columns],
  )

  /**
   * 明细表的行 —— 给每行补一个 key。
   *
   * ⚠️ antd 的 `rowKey` 函数**不再保证 index 参数** ——
   *    用 `(_, index) => String(index)` 会有弃用警告。
   *    自己补 key 更稳。
   */
  const tableRows = useMemo(
    () => (data?.rows ?? []).map((row, index) => ({ key: `row-${index}`, cells: row })),
    [data?.rows],
  )

  return (
    <div className="metric-chart-panel">
      {error && (
        <Alert type="error" showIcon message="预览失败" description={error} />
      )}

      {/* ⚠️ 时间窗口**只喂给 `$timefilter`** ——
          SQL 里自己写了时间条件（或压根没写），窗口就不生效（静默失效）。 */}
      {config.query && !config.query.includes('$timefilter') && (
        <p className="form-hint">
          SQL 里没有 $timefilter —— 「最近 N 个点」的时间窗口不生效
          （它只替换 $timefilter）。
        </p>
      )}

      {loading && !data && <Typography.Text type="secondary">正在取数…</Typography.Text>}

      <BrowseChart
        rows={data?.rows ?? []}
        columns={data?.columns ?? []}
        roles={roles}
        timeValues={data?.timeValues ?? null}
      />

      {data && (
        <>
          <Typography.Text type="secondary">
            {data.total} 行{data.truncated ? '（还有更多）' : ''} · {data.elapsed} ms ·
            窗口：最近 {windowPoints} 点 × {freq}
          </Typography.Text>
          <Table
            size="small"
            rowKey="key"
            dataSource={tableRows}
            pagination={{ pageSize: PAGE_SIZE, showSizeChanger: false, size: 'small' }}
            columns={tableColumns}
          />
        </>
      )}
    </div>
  )
}
