/** Lab 结果里的「窗口明细」表格列定义。 */
import { Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { LabWindow } from '../../api/types'
import { fmtDateTime } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import { metricClassLabel } from '../jobs/ClassificationCard'

export const WINDOW_COLUMNS: ColumnsType<LabWindow> = [
  {
    title: '窗口',
    dataIndex: 'index',
    width: 64,
    align: 'right',
    render: (value: number) => <span className="mono">{value}</span>,
  },
  {
    title: '时间范围',
    key: 'range',
    render: (_, row) => (
      <span className="mono">
        {fmtDateTime(row.start)} → {fmtDateTime(row.end)}
      </span>
    ),
  },
  {
    title: '点数',
    key: 'points',
    align: 'right',
    render: (_, row) => (
      <span className="mono">
        {row.n} / {row.expected}
      </span>
    ),
  },
  {
    title: '缺失',
    dataIndex: 'missing_ratio',
    align: 'right',
    render: (value: number) => <span className="mono">{(value * 100).toFixed(0)}%</span>,
  },
  {
    title: '零值',
    dataIndex: 'zero_ratio',
    align: 'right',
    render: (value: number) => <span className="mono">{(value * 100).toFixed(0)}%</span>,
  },
  {
    title: '网格',
    dataIndex: 'on_grid_ratio',
    align: 'right',
    render: (value: number) => <span className="mono">{(value * 100).toFixed(0)}%</span>,
  },
  {
    title: '重复',
    dataIndex: 'duplicate_timestamps',
    align: 'right',
    render: (value: number) => <span className="mono">{value}</span>,
  },
  {
    title: '状态',
    key: 'sufficient',
    render: (_, row) =>
      row.sufficient ? (
        <span className="pill pill--ok">充足</span>
      ) : (
        // ⚠️ 「不足」是**提醒**，不是告警 —— 用 p1 而不是 p0。
        //    整屏都是红色会盖掉真正要看的东西。
        <Tooltip title={row.insufficient_reason ?? '数据不足'}>
          <span className="pill pill--p1">不足</span>
        </Tooltip>
      ),
  },
  {
    title: '形态',
    key: 'shape',
    render: (_, row) =>
      row.classification ? (
        <span>
          {metricClassLabel(row.classification.metric_class)}
          <span className="muted mono"> · {row.classification.confidence.toFixed(2)}</span>
        </span>
      ) : (
        <Tooltip title={row.classification_reason ?? '未判定'}>
          <span className="muted">—</span>
        </Tooltip>
      ),
  },
  {
    title: '候选算法',
    key: 'candidates',
    render: (_, row) => (
      <span className="muted">
        {row.classification?.candidates.map(detectorLabel).join(' / ') ?? '—'}
      </span>
    ),
  },
]

