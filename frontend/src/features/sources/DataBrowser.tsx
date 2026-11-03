import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button, DatePicker, Input, Select, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { querySource } from '../../api/platform'
import { ROLE_OPTIONS, resolveRoles, roleOf, type RoleChoice } from './roles'
import type { SourceQueryResult } from '../../api/types'

const { RangePicker } = DatePicker
const { TextArea } = Input

/**
 * 时间格式的取值 —— 必须与后端 `SourceQueryIn.time_format` 一致。
 *
 * ⚠️ 浏览时**必须**跟着请求一起发 —— 浏览与指标运行时用同一套
 *    `$timefilter` 渲染（D11），浏览不声明的话，epoch / `iso_naive` 源的
 *    预览 ≠ 跑出来的。
 */
export const TIME_FORMAT_OPTIONS = [
  { value: 'iso_utc', label: 'iso_utc' },
  { value: 'iso_naive', label: 'iso_naive' },
  { value: 'epoch_s', label: 'epoch_s' },
  { value: 'epoch_ms', label: 'epoch_ms' },
]

/** 单元格的值 → 文本。空值显示成破折号，别显示 "null"。 */
function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  return String(value)
}

/** 表格的一行 —— 原始行是数组，包一层是为了给 rowKey 用。 */
interface BrowserRow {
  key: string
  row: unknown[]
}

/**
 * 时间边界 → ISO 字符串。
 *
 * ⚠️ 后端用 `datetime.fromisoformat` 解析 —— 直接 `String(dayjs)` 出来的
 *    不是 ISO，解析会炸。
 */
function toIso(value: Dayjs | null): string | undefined {
  if (!value) return undefined
  return value.toISOString()
}

/** 「用这个结果建指标」带回去的东西。 */
export interface BrowserResult {
  sql: string
  columns: SourceQueryResult['columns']
  roles: {
    time_column?: string
    value_column?: string
    group_column?: string
  }
  time_format: string
  source_timezone: string
}

export interface DataBrowserProps {
  sourceId: number
  /** 数据源类型 —— 决定渲染 SQL 编辑器还是该源专属表单（spec §6.4）。 */
  kind: string
  /** 初始 SQL —— 从指标配置带过来 */
  initialSql?: string
  /** 初始时间列 */
  initialTimeColumn?: string
  /** 初始时间格式 */
  initialTimeFormat?: string
  /** 初始源时区 */
  initialSourceTimezone?: string
  /** 已知列角色（编辑已有指标时预置） */
  initialAssignments?: Record<string, RoleChoice>
  /**
   * 结果跑出来之后的动作 —— 「用这个结果建指标」。
   *
   * ⚠️ 可选：预览页自己决定下一步（保存回指标 / 带回表单）。
   */
  onUseAsMetric?: (payload: BrowserResult) => void
  /** 「用这个结果建指标」按钮的文案 */
  useAsLabel?: string
  /**
   * 编辑器里的当前状态。
   *
   * ⚠️ 页面上的「保存」按钮要拿到**用户改过**的 SQL 与列指派 ——
   *    它在浏览器外面，只能靠回调拿。
   */
  onStateChange?: (state: {
    sql: string
    timeColumn: string
    timeFormat: string
    sourceTimezone: string
    assignments: Record<string, RoleChoice>
  }) => void
  /**
   * 跑出来的结果（含列角色解析）。
   *
   * ⚠️ 只有跑过查询才有 —— 保存按钮靠它决定能不能点。
   */
  onResult?: (payload: BrowserResult) => void
  /**
   * 打开就执行一次。
   *
   * ⚠️ 预览页要这样 —— 打开空着等用户点「执行」，
   *    「预览」这件事就没有意义了。
   */
  autoRun?: boolean
}

/**
 * 数据浏览器 —— 在数据源上跑一段**只读**查询，看几行原始数据。
 *
 * ⚠️ 目的是「先看结构、再定指标」—— 用户不该闭着眼睛写 SQL。
 *
 * ⚠️ 它住在**指标的编辑流程里**（预览页），不占数据源详情页的位置 ——
 *    数据的用途就是定指标，放在数据源页上只是个孤立的工具。
 */
export function DataBrowser({
  sourceId,
  kind,
  initialSql,
  initialTimeColumn,
  initialTimeFormat,
  initialSourceTimezone,
  initialAssignments,
  onUseAsMetric,
  useAsLabel = '用这个结果建指标',
  onStateChange,
  onResult,
  autoRun = false,
}: DataBrowserProps) {
  const [sql, setSql] = useState(initialSql ?? 'SELECT * FROM metrics LIMIT 100')
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [timeColumn, setTimeColumn] = useState<string>(initialTimeColumn ?? '')
  /** 时间格式 —— 缺省与后端一致（iso_utc）。 */
  const [timeFormat, setTimeFormat] = useState<string>(initialTimeFormat ?? 'iso_utc')
  /** 源时区 —— 缺省与后端一致（UTC）。 */
  const [sourceTimezone, setSourceTimezone] = useState<string>(initialSourceTimezone ?? 'UTC')
  /** 列名 → 用户指派的角色（没指派过的列走自动推断）。 */
  const [assignments, setAssignments] = useState<Record<string, RoleChoice>>(initialAssignments ?? {})

  /**
   * 初值同步。
   *
   * ⚠️ 指标配置是**异步**取到的（catalog 请求回来之前先渲染）——
   *    不同步的话，编辑指标时打开预览页看到的是默认 SQL，不是这个指标的 SQL。
   */
  useEffect(() => {
    if (initialSql != null) setSql(initialSql)
  }, [initialSql])
  useEffect(() => {
    if (initialTimeColumn != null) setTimeColumn(initialTimeColumn)
  }, [initialTimeColumn])
  useEffect(() => {
    if (initialTimeFormat != null) setTimeFormat(initialTimeFormat)
  }, [initialTimeFormat])
  useEffect(() => {
    if (initialSourceTimezone != null) setSourceTimezone(initialSourceTimezone)
  }, [initialSourceTimezone])
  useEffect(() => {
    if (initialAssignments) setAssignments(initialAssignments)
  }, [initialAssignments])

  const run = useMutation({
    mutationFn: () =>
      querySource(sourceId, {
        sql,
        limit: 100,
        time_column: timeColumn || undefined,
        // ⚠️ 时间格式与源时区必须一起发 —— 否则浏览与指标运行时的
        //    `$timefilter` 条件不一样，预览 ≠ 跑出来的（D11）。
        time_format: timeFormat,
        source_timezone: sourceTimezone,
        start: toIso(range?.[0] ?? null),
        end: toIso(range?.[1] ?? null),
      }),
  })

  const result = run.data

  /**
   * 打开就跑一次。
   *
   * ⚠️ 用 ref 守卫 —— effect 会因为依赖变化重跑，
   *    每跑一次都是一次多余的查询。
   * ⚠️ SQL 为空时**不跑** —— 指标配置是异步取到的，
   *    空 SQL 跑一次只会报错，等真 SQL 到了再跑。
   */
  const autoRan = useRef(false)
  useEffect(() => {
    if (!autoRun || autoRan.current) return
    if (!sql.trim()) return
    autoRan.current = true
    run.mutate()
    // ⚠️ run 是每次渲染的新对象 —— 不放进依赖里，靠 ref 守卫只跑一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, sql])

  /**
   * 把状态报给外面。
   *
   * ⚠️ 回调用 ref 存 —— 否则父组件每次渲染都给新函数，
   *    effect 会被反复触发（父组件 setState → 重渲染 → 又触发）。
   */
  const onStateChangeRef = useRef(onStateChange)
  onStateChangeRef.current = onStateChange
  const onResultRef = useRef(onResult)
  onResultRef.current = onResult

  useEffect(() => {
    onStateChangeRef.current?.({
      sql,
      timeColumn,
      timeFormat,
      sourceTimezone,
      assignments,
    })
  }, [sql, timeColumn, timeFormat, sourceTimezone, assignments])

  // 跑出结果时报告一次 —— 带着解析后的列角色
  useEffect(() => {
    if (!result) return
    onResultRef.current?.({
      sql,
      columns: result.columns,
      roles: resolveRoles(result.columns, assignments),
      time_format: timeFormat,
      source_timezone: sourceTimezone,
    })
  }, [result, sql, assignments, timeFormat, sourceTimezone])

  /** 指派某一列的角色 —— 一个角色只能属于一列。 */
  const assign = (columnName: string, choice: RoleChoice) => {
    setAssignments((prev) => {
      const next = { ...prev, [columnName]: choice }
      if (choice !== 'none') {
        for (const [name, role] of Object.entries(next)) {
          if (name !== columnName && role === choice) delete next[name]
        }
      }
      return next
    })
  }

  /**
   * 行是**数组**（列名在 columns 里）—— dataIndex 按列名取不到，只能按**位置**取。
   *
   * ⚠️ 包一层对象是为了给 rowKey 用 —— antd 的 rowKey 不接受数组行，
   *    而 rowKey 回调的 `index` 参数已废弃。
   */
  const rows = (result?.rows ?? []).map((row, index) => ({ key: String(index), row }))

  const columns: ColumnsType<BrowserRow> = (result?.columns ?? []).map((col, colIndex) => ({
    title: (
      <Space direction="vertical" size={2}>
        <Space size={6}>
          <span>{col.name}</span>
          <span className="muted mono">{col.type}</span>
        </Space>
        {/* ⚠️ 列 → 角色：自动推断只是默认值，用户能改。 taste-skill-ignore */}
        <Select
          size="small"
          variant="borderless"
          value={roleOf(result?.columns ?? [], assignments, col.name)}
          options={ROLE_OPTIONS}
          onChange={(choice) => assign(col.name, choice)}
          title={`${col.name} 列的角色`}
          style={{ width: 92 }}
        />
      </Space>
    ),
    key: col.name,
    // ⚠️ 数字列右对齐 —— 纵向比得准
    align: col.type === 'INTEGER' || col.type === 'REAL' ? 'right' : 'left',
    render: (_value: unknown, record: BrowserRow) => (
      <span className="mono">{formatCell(record.row[colIndex])}</span>
    ),
  }))

  /** 时间列的类型 —— INTEGER 说明它是 epoch 存的。 */
  // ⚠️ 时间列有两个来源：列头下拉的**指派**，与「时间列」输入框。
  //    两个都要看 —— 用户用哪个都行，但时间格式得跟着对。
  const assignedTimeColumn = resolveRoles(result?.columns ?? [], assignments).time_column
  const integerTimeColumn = [assignedTimeColumn, timeColumn]
    .filter((name): name is string => Boolean(name))
    .find((name) => result?.columns.find((col) => col.name === name)?.type === 'INTEGER')

  // ⚠️ spec §6.4：SQL 型源才渲染 SQL 编辑器 ——
  //    第二层连接器（未来）显示该源专属表单，不显示编辑器。
  if (kind !== 'sqlite' && kind !== 'http') {
    return (
      <section className="panel">
        <p className="muted">该数据源类型（{kind}）暂不支持 SQL 浏览。</p>
      </section>
    )
  }

  return (
    <section className="panel">
      <TextArea
        rows={5}
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        spellCheck={false}
        placeholder="SELECT ts, value FROM metrics WHERE ts >= {start}"
      />
      <Space wrap style={{ margin: '12px 0' }}>
        <RangePicker onChange={(value) => setRange(value)} />
        <Input
          placeholder="时间列（SQL 含 $timefilter 时必填）"
          value={timeColumn}
          onChange={(e) => setTimeColumn(e.target.value)}
          style={{ width: 280 }}
        />
        <Select
          value={timeFormat}
          options={TIME_FORMAT_OPTIONS}
          onChange={(value) => setTimeFormat(value)}
          title="时间格式"
          style={{ width: 140 }}
        />
        <Input
          placeholder="源时区（默认 UTC）"
          value={sourceTimezone}
          onChange={(e) => setSourceTimezone(e.target.value)}
          style={{ width: 170 }}
          title="源时区"
        />
        <Button type="primary" loading={run.isPending} onClick={() => run.mutate()}>
          执行
        </Button>
      </Space>

      {/* ⚠️ INTEGER 的时间列是 epoch 存的 —— 用 iso 解释会静默落到 1970 年。 taste-skill-ignore */}
      {integerTimeColumn && (
        <p className="form-error">
          时间列「{integerTimeColumn}」是 INTEGER —— 时间格式要选 epoch_s / epoch_ms。
        </p>
      )}

      {run.error instanceof Error && <p className="form-error">{run.error.message}</p>}

      {result && (
        <>
          <Typography.Text type="secondary">
            {result.columns.length} 列 · {result.total} 行
            {result.truncated ? '（还有更多）' : ''} · {result.elapsed_ms} ms
          </Typography.Text>
          <Table
            size="small"
            rowKey="key"
            dataSource={rows}
            pagination={false}
            columns={columns}
          />
          {onUseAsMetric ? (
            <Button
              onClick={() =>
                onUseAsMetric({
                  sql,
                  columns: result.columns,
                  roles: resolveRoles(result.columns, assignments),
                  time_format: timeFormat,
                  source_timezone: sourceTimezone,
                })
              }
            >
              {useAsLabel}
            </Button>
          ) : null}
        </>
      )}
    </section>
  )
}
