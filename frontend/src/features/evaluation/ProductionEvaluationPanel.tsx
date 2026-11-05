import { useState } from 'react'
import { Alert, InputNumber, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import { fmtMetric, fmtUtcTime } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import { useProductionEvaluation } from './queries'
import type {
  ProductionEvaluation,
  ProductionEvaluationRow,
  ProductionLayer,
} from '../../api/types'

/**
 * 生产检测记录的评估。
 *
 * ⚠️ **这是分层抽样估计，不是「样本的成绩」**：
 *   候选 = 全部运行记录 × 全部序列；
 *   按「数据源 → 指标 → 检出结果（正常/异常）」分层；
 *   每层用自己的采样率抽一部分去标注；
 *   评估时按每条标注自带的**采样率**反算总体量，再算 P / R / F1。
 *
 * ⚠️ **正常层是估漏报的唯一来源** —— 只标异常记录的话漏报永远是 0。
 */
export function ProductionEvaluationPanel() {
  const [rateAlert, setRateAlert] = useState(50)
  const [rateNormal, setRateNormal] = useState(5)
  const [maxPerLayer, setMaxPerLayer] = useState(10)
  const query = useProductionEvaluation(
    undefined,
    rateAlert / 100,
    rateNormal / 100,
    maxPerLayer,
  )
  const data = query.data

  const layerColumns: ColumnsType<ProductionLayer> = [
    {
      title: '数据源',
      dataIndex: 'source_name',
    },
    {
      title: '指标',
      dataIndex: 'metric_name',
    },
    {
      title: '检出结果',
      dataIndex: 'outcome_label',
      render: (value: string, row) => (
        <Tag color={row.outcome === 'alert' ? 'volcano' : 'default'}>{value}</Tag>
      ),
    },
    {
      title: '检测记录 / 告警事件',
      key: 'counts',
      align: 'right',
      render: (_, row) => (
        <span className="mono">
          {row.n_candidates} / {row.n_events}
        </span>
      ),
    },
    {
      title: '采样 / 有真值',
      key: 'sampled',
      align: 'right',
      render: (_, row) => (
        <span className="mono">
          {row.n_sampled} / {row.n_annotated}
        </span>
      ),
    },
    {
      title: 'Precision',
      dataIndex: 'precision',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: 'Recall',
      dataIndex: 'recall',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: 'F1',
      dataIndex: 'f1',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: '区间 F1',
      dataIndex: 'range_f1',
      align: 'right',
      render: (value: number | null) => <span className="mono">{fmtMetric(value)}</span>,
    },
  ]

  const rowColumns: ColumnsType<ProductionEvaluationRow> = [
    {
      title: '序列',
      dataIndex: 'series_id',
      render: (value: string, row) => (
        <Link
          to={`/detections?series_id=${encodeURIComponent(value)}&detector=${encodeURIComponent(row.detector)}`}
        >
          {value}
        </Link>
      ),
    },
    {
      title: '指标',
      dataIndex: 'metric_name',
      render: (value: string, row) => (
        <span>
          {value}
          <span className="muted mono"> · {row.source_name}</span>
        </span>
      ),
    },
    {
      title: '检出结果',
      dataIndex: 'outcome_label',
      render: (value: string, row) => (
        <Tag color={row.outcome === 'alert' ? 'volcano' : 'default'}>{value}</Tag>
      ),
    },
    {
      title: '算法',
      dataIndex: 'detector',
      render: (value: string) => <Tag>{detectorLabel(value)}</Tag>,
    },
    {
      title: '运行',
      dataIndex: 'run_id',
      align: 'right',
      render: (value: number, row) => (
        <span className="mono">
          #{value} · {fmtUtcTime(row.start_ts)} → {fmtUtcTime(row.end_ts)}
        </span>
      ),
    },
    {
      title: '标注',
      dataIndex: 'n_annotations',
      align: 'right',
      render: (value: number, row) => (
        <span className="mono">
          {value} 段 / {row.n_truth} 点
        </span>
      ),
    },
    {
      title: '采样率 → 权重',
      dataIndex: 'rate',
      align: 'right',
      render: (value: number, row) => (
        <span className="mono">
          {(value * 100).toFixed(0)}% → ×{row.weight.toFixed(1)}
        </span>
      ),
    },
    {
      title: '命中 / 误报 / 漏报',
      key: 'counts',
      align: 'right',
      render: (_, row) => (
        <span className="mono">
          {row.tp} / {row.fp} / {row.fn}
        </span>
      ),
    },
    {
      title: 'Precision',
      dataIndex: 'precision',
      align: 'right',
      render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: 'Recall',
      dataIndex: 'recall',
      align: 'right',
      render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
    },
    {
      title: 'F1',
      dataIndex: 'f1',
      align: 'right',
      render: (value: number) => <span className="mono">{fmtMetric(value)}</span>,
    },
  ]

  return (
    <section className="panel">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">生产检测记录</h2>
        </div>
        <div className="production__rate">
          <span>异常层</span>
          <InputNumber
            min={1}
            max={100}
            step={5}
            value={rateAlert}
            onChange={(value) => setRateAlert(value ?? 50)}
            addonAfter="%"
            style={{ width: 96 }}
          />
          <span>正常层</span>
          <InputNumber
            min={1}
            max={100}
            step={1}
            value={rateNormal}
            onChange={(value) => setRateNormal(value ?? 5)}
            addonAfter="%"
            style={{ width: 96 }}
          />
          <span>每层最多</span>
          <InputNumber
            min={1}
            max={200}
            value={maxPerLayer}
            onChange={(value) => setMaxPerLayer(value ?? 10)}
            addonAfter="条"
            style={{ width: 96 }}
          />
        </div>
      </div>

      <StateBoundary<ProductionEvaluation>
        isLoading={query.isPending}
        error={query.error}
        data={data}
        isEmpty={(value) => value.rows.length === 0}
        emptyTitle="还没有可评估的生产检测记录"
        emptyHint="先让告警任务跑起来，再去「标注」页标一段"
      >
        {(value) => (
          <>
            {value.warnings.length > 0 && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message={value.warnings.join('；')}
              />
            )}

            <div className="evaluation__overall kpis kpis--eval">
              <div className="kpi">
                <span className="kpi__k">候选</span>
                <span className="kpi__v num">{value.sampling.n_candidates}</span>
                <span className="kpi__s">全部运行记录 × 全部序列</span>
              </div>
              <div className="kpi">
                <span className="kpi__k">告警事件</span>
                <span className="kpi__v num">{value.sampling.n_events}</span>
                <span className="kpi__s">同一区间只算一个</span>
              </div>
              <div className="kpi">
                <span className="kpi__k">采样</span>
                <span className="kpi__v num">{value.sampling.n_sampled}</span>
                <span className="kpi__s">
                  异常 {(value.sampling.rate_alert * 100).toFixed(0)}% · 正常{' '}
                  {(value.sampling.rate_normal * 100).toFixed(0)}%
                </span>
              </div>
              <div className="kpi">
                <span className="kpi__k">已标注</span>
                <span className="kpi__v num">{value.sampling.n_annotated}</span>
                <span className="kpi__s">按各自采样率反算总体</span>
              </div>
              <div className="kpi">
                <span className="kpi__k">Precision</span>
                <span className="kpi__v num">{fmtMetric(value.overall.precision)}</span>
                <span className="kpi__s">告警中真异常占比</span>
              </div>
              <div className="kpi">
                <span className="kpi__k">Recall</span>
                <span className="kpi__v num">{fmtMetric(value.overall.recall)}</span>
                <span className="kpi__s">真异常被检出占比</span>
              </div>
              <div className="kpi">
                <span className="kpi__k">F1</span>
                <span className="kpi__v num">{fmtMetric(value.overall.f1)}</span>
                <span className="kpi__s">
                  估计总体 {value.overall.n_estimated.toLocaleString()} 条
                </span>
              </div>
            </div>

            <h3 className="production__section-title">分层表现</h3>
            <Table
              size="small"
              rowKey={(row) => `${row.source_id}-${row.metric_id}-${row.outcome}`}
              columns={layerColumns}
              dataSource={value.layers}
              pagination={false}
              scroll={{ x: 'max-content' }}
            />

            <h3 className="production__section-title">已标注的记录</h3>
            <Table
              size="small"
              rowKey={(row) => `${row.run_id}-${row.series_id}`}
              columns={rowColumns}
              dataSource={value.rows}
              pagination={{ pageSize: 20, showSizeChanger: true }}
              scroll={{ x: 'max-content' }}
            />
          </>
        )}
      </StateBoundary>
    </section>
  )
}
