import { Button, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { CompareDetector } from '../../api/types'
import { seriesColors } from './CompareChart'

export interface CompareTableProps {
  detectors: CompareDetector[]
  levels: string[]
  applyingDetector: string | null
  onApplyDetector: (name: string) => void
}

/**
 * 最高档的档位序号。
 *
 * ⚠️ `severity` 全是 0 时没有告警 —— 返回 0（对应「正常」档）。
 */
export function topSeverityOf(severity: number[]): number {
  return severity.length ? Math.max(...severity) : 0
}

/**
 * 最高分。**必须过滤 null**，否则 `Math.max` 得到 NaN。
 *
 * 全部为 null 时返回 null（显示「—」）。
 */
export function maxScoreOf(scores: (number | null)[]): number | null {
  return scores.reduce<number | null>(
    (acc, s) => (s == null ? acc : acc == null ? s : Math.max(acc, s)),
    null,
  )
}

/**
 * 对比表。
 *
 * 列（照搬旧 `renderCompareTable`，另按 spec §8.2-A 补齐）：
 *   算法 / 自动推荐 / 告警数 / **最高档** / **最高档点数** / 最高分 / 惯用倍数 / 操作
 *
 * ⚠️ `n_top` 是**点数**不是档位序号 —— 后端算的是
 *    `n_top = int((severity == top_level).sum())`（`platform/compare.py`）。
 *    旧 UI 的「最高档」列显示的其实就是这个点数（列名与内容不符），
 *    新实现拆成「最高档」（档位名）与「最高档点数」（点数）两列。
 */
export function CompareTable({
  detectors,
  levels,
  applyingDetector,
  onApplyDetector,
}: CompareTableProps) {
  const colors = seriesColors()

  const columns: ColumnsType<CompareDetector> = [
    {
      title: '算法',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, row) => {
        const index = detectors.findIndex((d) => d.name === row.name)
        const color = colors[index % colors.length]
        return (
          <span className="mono">
            <span className="compare-table__dot" style={{ background: color }} />
            {value}
          </span>
        )
      },
    },
    {
      title: '自动推荐',
      dataIndex: 'is_auto',
      key: 'is_auto',
      width: 110,
      render: (value: boolean) => (value ? '✓ 自动推荐' : ''),
    },
    {
      title: '告警数',
      dataIndex: 'n_alerts',
      key: 'n_alerts',
      width: 90,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '最高档',
      key: 'top_level',
      width: 90,
      render: (_value, row) => {
        const severity = topSeverityOf(row.severity)
        return <span className="mono">{levels[severity] ?? '-'}</span>
      },
    },
    {
      title: '最高档点数',
      dataIndex: 'n_top',
      key: 'n_top',
      width: 110,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '最高分',
      key: 'max_score',
      width: 90,
      align: 'right',
      render: (_value, row) => {
        const max = maxScoreOf(row.scores)
        return <span className="mono">{max === null ? '—' : max.toFixed(2)}</span>
      },
    },
    {
      title: '惯用倍数',
      dataIndex: 'default_threshold',
      key: 'default_threshold',
      width: 100,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_value, row) => (
        <Tooltip title="把这个算法设为该任务的检测算法">
          <Button
            size="small"
            loading={applyingDetector === row.name}
            onClick={() => onApplyDetector(row.name)}
          >
            设为任务算法
          </Button>
        </Tooltip>
      ),
    },
  ]

  return (
    <Table<CompareDetector>
      rowKey="name"
      columns={columns}
      dataSource={detectors}
      size="middle"
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{ emptyText: '没有可对比的算法' }}
    />
  )
}

/** 对比区上方的结论摘要（照搬旧 `renderCompareTable` 的 hint 文案）。 */
export function CompareSummary({
  metricClass,
  confidence,
  autoDetector,
  autoFallback,
  recommended,
}: {
  metricClass: string | null
  confidence: number | null
  autoDetector: string
  autoFallback: boolean
  recommended: string[]
}) {
  const confidenceText = confidence === null ? '—' : confidence.toFixed(2)
  return (
    <p className="muted compare-summary">
      形态 {metricClass || '未判定'}（置信度 {confidenceText}） · auto 选用 {autoDetector}
      {autoFallback ? '（回退）' : ''} · 推荐候选 {recommended.join('/') || '—'}
    </p>
  )
}
