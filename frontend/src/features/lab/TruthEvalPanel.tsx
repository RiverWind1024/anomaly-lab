import { Alert, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { LabEvaluateResult } from '../../api/types'
import { detectorLabel } from '../../lib/detectorLabels'

export interface TruthEvalPanelProps {
  result: LabEvaluateResult
}

/** F1 之类的小数 —— 三位就够看了。 */
const pct = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : value.toFixed(3)

/**
 * 有真值评估的结果。
 *
 * ⚠️ **校准与测试必须并排看** —— 校准 F1 明显高于测试 F1，
 *    说明阈值是在这批数据上「抠」出来的，换一批就不灵。
 */
export function TruthEvalPanel({ result }: TruthEvalPanelProps) {
  const rows = result.results

  const columns: ColumnsType<(typeof rows)[number]> = [
    {
      title: '算法',
      dataIndex: 'detector',
      render: (value: string, row) => {
        const mix = Object.entries(row.resolved_mix ?? {})
        // ⚠️ `auto` 常常就解析成某个固定算法 —— 两行数字一模一样，
        //    不说清楚的话用户会以为跑出了两个不同的结果。
        const resolved = mix.length === 1 ? mix[0][0] : null
        const sameAsResolved = resolved !== null && resolved === value
        if (!resolved || sameAsResolved) return detectorLabel(value)
        return (
          <span>
            {detectorLabel(value)}
            <span className="lab-eval__resolved"> → {detectorLabel(resolved)}</span>
          </span>
        )
      },
    },
    {
      title: '校准阈值',
      key: 'calibration_threshold',
      align: 'right',
      render: (_, row) => (
        <span className="mono">
          {row.calibration.threshold === null ? '—' : row.calibration.threshold.toFixed(2)}
        </span>
      ),
    },
    {
      title: '校准 F1',
      key: 'calibration_f1',
      align: 'right',
      render: (_, row) => <span className="mono">{pct(row.calibration.metrics?.f1)}</span>,
    },
    {
      title: '测试 F1',
      key: 'test_f1',
      align: 'right',
      render: (_, row) => <span className="mono">{pct(row.test?.f1)}</span>,
    },
    {
      title: '测试区间 F1',
      key: 'test_range_f1',
      align: 'right',
      render: (_, row) => <span className="mono">{pct(row.test?.range_f1)}</span>,
    },
    {
      title: '平台默认阈值 F1',
      key: 'default_f1',
      align: 'right',
      render: (_, row) => <span className="mono">{pct(row.default_threshold?.f1)}</span>,
    },
    {
      title: '检出点 / 真值点',
      key: 'counts',
      align: 'right',
      render: (_, row) => (
        <span className="mono">
          {row.test?.n_alerts ?? 0} / {row.test?.n_truth ?? 0}
        </span>
      ),
    },
  ]

  return (
    <>
      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">有真值评估</h2>
          </div>
          <div className="lab-eval__facts">
            <span className="mono">
              真值 {result.truth.n_truth_points} 点 · {result.truth.n_series_with_truth} 条序列
            </span>
            <span className="mono">
              校准 {result.split.calibration_windows} 窗 · 测试 {result.split.test_windows} 窗
            </span>
          </div>
        </div>

        {result.warnings.length > 0 && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={result.warnings.join('；')}
          />
        )}

        <Table
          size="small"
          rowKey="detector"
          columns={columns}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 860 }}
          expandable={{
            rowExpandable: (row) => row.sensitivity.length > 0,
            expandedRowRender: (row) => (
              <Table
                size="small"
                rowKey={(item) => String(item.threshold)}
                pagination={false}
                dataSource={row.sensitivity}
                columns={[
                  { title: '阈值', dataIndex: 'threshold', align: 'right', width: 80 },
                  { title: '测试 F1', dataIndex: 'f1', align: 'right', width: 90 },
                  { title: '区间 F1', dataIndex: 'range_f1', align: 'right', width: 90 },
                  { title: '检出点', dataIndex: 'n_alerts', align: 'right', width: 80 },
                ]}
              />
            ),
          }}
        />
      </section>
    </>
  )
}
