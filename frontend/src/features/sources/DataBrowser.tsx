import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button, Card, DatePicker, Input, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { querySource } from '../../api/platform'
import type { SourceQueryResult } from '../../api/types'

const { RangePicker } = DatePicker
const { TextArea } = Input

/** 单元格的值 → 文本。空值显示成破折号，别显示 "null"。 */
function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  return String(value)
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

/**
 * 数据浏览器。
 *
 * ⚠️ 目的是「先看结构、再定指标」—— 用户不该闭着眼睛写 SQL。
 */
export function DataBrowser({
  sourceId,
  onUseAsMetric,
}: {
  sourceId: number
  onUseAsMetric: (payload: {
    sql: string
    columns: SourceQueryResult['columns']
  }) => void
}) {
  const [sql, setSql] = useState('SELECT * FROM metrics LIMIT 100')
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [timeColumn, setTimeColumn] = useState<string>('')

  const run = useMutation({
    mutationFn: () =>
      querySource(sourceId, {
        sql,
        limit: 100,
        time_column: timeColumn || undefined,
        start: toIso(range?.[0] ?? null),
        end: toIso(range?.[1] ?? null),
      }),
  })

  const result = run.data

  // ⚠️ 行是**数组**（列名在 columns 里）—— dataIndex 按列名取不到，
  //    只能按**位置**取。
  const columns: ColumnsType<unknown[]> = (result?.columns ?? []).map((col, colIndex) => ({
    title: (
      <Space direction="vertical" size={0}>
        <span>{col.name}</span>
        <span className="muted mono">{col.type}</span>
      </Space>
    ),
    key: col.name,
    render: (_value: unknown, row: unknown[]) => (
      <span className="mono">{formatCell(row[colIndex])}</span>
    ),
  }))

  return (
    <Card size="small" title="浏览数据" className="data-browser">
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
        <Button type="primary" loading={run.isPending} onClick={() => run.mutate()}>
          执行
        </Button>
      </Space>

      {run.error instanceof Error && <p className="form-error">{run.error.message}</p>}

      {result && (
        <>
          <Typography.Text type="secondary">
            {result.columns.length} 列 · 共 {result.total} 行（显示 {result.rows.length} 行）·
            {result.elapsed_ms} ms
          </Typography.Text>
          <Table
            size="small"
            rowKey={(_row, index) => String(index)}
            dataSource={result.rows}
            pagination={false}
            scroll={{ x: 'max-content' }}
            columns={columns}
          />
          <Button onClick={() => onUseAsMetric({ sql, columns: result.columns })}>
            用这个结果建指标
          </Button>
        </>
      )}
    </Card>
  )
}
