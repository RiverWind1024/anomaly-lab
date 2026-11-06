import { Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { detectorLabel } from '../../lib/detectorLabels'
import { fmtDateTime } from '../../lib/format'
import { metricClassLabel } from '../jobs/ClassificationCard'
import { SensitivityChart } from './SensitivityChart'
import { WindowDetailPanel } from './WindowDetailPanel'
import type { LabDetectorRun, LabRunResult } from '../../api/types'

/**
 * 多算法对比面板 —— P1 的主视图。
 *
 * 这一屏回答三个问题：
 *   1. **哪个算法检出得多**（量）
 *   2. **哪个算法稳**（跨窗一致性 + 倍数敏感性）
 *   3. **auto 到底在干什么**（逐窗实际用了什么算法）
 *
 * ⚠️ 没有真值 —— 所以**不显示 F1**，只给「检出画像 + 取舍」。
 */

/** 聚合表：每个检测器一行。 */
function AggregateTable({ runs }: { runs: LabDetectorRun[] }) {
  const columns: ColumnsType<LabDetectorRun> = [
    {
      title: '算法',
      dataIndex: 'detector',
      render: (value: string) => (
        <span>
          <strong>{detectorLabel(value)}</strong>
          <span className="muted mono"> · {value}</span>
        </span>
      ),
    },
    {
      title: '检出点',
      key: 'n_alerts',
      align: 'right',
      render: (_, row) => <span className="mono">{row.aggregate.n_alerts}</span>,
    },
    {
      title: '检出率',
      key: 'alert_ratio',
      align: 'right',
      render: (_, row) => (
        <span className="mono">{(row.aggregate.alert_ratio * 100).toFixed(2)}%</span>
      ),
    },
    {
      title: '有检出的窗口',
      key: 'n_windows_with_alerts',
      align: 'right',
      render: (_, row) => (
        <span className="mono">
          {row.aggregate.n_windows_with_alerts} / {row.aggregate.n_windows}
        </span>
      ),
    },
    {
      title: '稳定性',
      key: 'stability',
      align: 'right',
      // ⚠️ 数值**越小越稳**（各窗口检出率的离散度）—— 别让人误读成「越大越好」
      render: (_, row) => (
        <Tooltip title="各窗口检出率的离散度 —— 越小说明这个算法在窗口之间表现越一致">
          <span className="mono">
            {row.aggregate.stability === null ? '—' : row.aggregate.stability.toFixed(4)}
          </span>
        </Tooltip>
      ),
    },
    {
      title: '耗时',
      key: 'elapsed_ms',
      align: 'right',
      render: (_, row) => <span className="mono">{row.aggregate.elapsed_ms.toFixed(1)} ms</span>,
    },
    {
      title: '实际用的算法',
      key: 'resolved_mix',
      render: (_, row) => (
        <span className="muted">
          {Object.entries(row.aggregate.resolved_mix)
            .map(([name, count]) => `${detectorLabel(name)}×${count}`)
            .join(' · ') || '—'}
        </span>
      ),
    },
  ]

  return (
    <Table<LabDetectorRun>
      size="small"
      rowKey="detector"
      columns={columns}
      dataSource={runs}
      pagination={false}
      scroll={{ x: 860 }}
    />
  )
}

/** 逐窗明细：每个检测器一列，并排看检出数。 */
function PerWindowTable({ result }: { result: LabRunResult }) {
  const runs = result.results

  /** (series_id, window_index) → 该检测器的窗口结果 */
  const lookup = new Map<string, Map<string, (typeof runs)[number]['per_window'][number]>>()
  runs.forEach((run) => {
    const inner = new Map<string, (typeof runs)[number]['per_window'][number]>()
    run.per_window.forEach((item) => inner.set(item.series_id + '@' + item.window_index, item))
    lookup.set(run.detector, inner)
  })

  const columns: ColumnsType<(typeof result.windows)[number]> = [
    {
      title: '序列',
      dataIndex: 'series_id',
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '窗口',
      dataIndex: 'index',
      width: 56,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '时间范围（本地时间）',
      key: 'range',
      render: (_, row) => (
        <span className="mono">
          {fmtDateTime(row.start)} → {fmtDateTime(row.end)}
        </span>
      ),
    },
    {
      title: '点数',
      key: 'n',
      align: 'right',
      render: (_, row) => (
        <span className="mono">
          {row.n} / {row.expected}
        </span>
      ),
    },
    ...runs.map((run) => ({
      title: detectorLabel(run.detector),
      key: run.detector,
      align: 'right' as const,
      render: (_: unknown, row: (typeof result.windows)[number]) => {
        const item = lookup.get(run.detector)?.get(row.series_id + '@' + row.index)
        if (!item) return <span className="muted">—</span>
        if (item.skipped) {
          return (
            <Tooltip title={item.skip_reason ?? '数据不足'}>
              <span className="muted">跳过</span>
            </Tooltip>
          )
        }
        return (
          <Tooltip
            title={
              run.detector === 'auto'
                ? `这一窗判定为${metricClassLabel(item.metric_class)}，实际用 ${detectorLabel(item.detector)}`
                : item.rationale || undefined
            }
          >
            <span className="mono">
              {item.n_alerts}
              {run.detector === 'auto' ? (
                <span className="muted"> · {detectorLabel(item.detector)}</span>
              ) : null}
            </span>
          </Tooltip>
        )
      },
    })),
  ]

  return (
    <Table
      size="small"
      rowKey={(row) => row.series_id + '@' + row.index}
      columns={columns}
      dataSource={result.windows}
      pagination={false}
      scroll={{ x: 900 }}
      expandable={{
        rowExpandable: (row) => row.n > 0,
        expandedRowRender: (row) => (
          <WindowDetailPanel
            spec={result.spec}
            seriesId={row.series_id}
            windowIndex={row.index}
            detectors={runs.map((run) => run.detector)}
          />
        ),
      }}
    />
  )
}

export function ExperimentPanel({ result }: { result: LabRunResult }) {
  return (
    <>
      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">算法对比</h2>
          </div>
        </div>
        <AggregateTable runs={result.results} />
      </section>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">倍数敏感性</h2>
          </div>
        </div>
        <SensitivityChart runs={result.results} multipliers={result.multipliers} />
      </section>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">逐窗明细</h2>
          </div>
        </div>
        <PerWindowTable result={result} />
      </section>
    </>
  )
}
