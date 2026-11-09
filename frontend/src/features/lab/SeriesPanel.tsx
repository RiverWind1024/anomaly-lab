/** Lab 结果里的单条序列面板。 */
import { Collapse, Table } from 'antd'
import type { LabSeries, LabWindow } from '../../api/types'
import { fmtDateTime } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import { metricClassLabel } from '../jobs/ClassificationCard'
import { WINDOW_COLUMNS } from './windowColumns'

export function SeriesPanel({ series }: { series: LabSeries }) {
  const shape = series.shape
  return (
    <section className="panel lab-series">
      <div className="panel__head">
        <div>
          <h2 className="panel__title mono">{series.series_id}</h2>
          <p className="panel__meta">
            {series.n} 个点 · {series.windows.length} 个采样窗口
            {series.data_start && series.data_end ? (
              <>
                {' · 数据实际覆盖 '}
                <span className="mono">
                  {fmtDateTime(series.data_start)} → {fmtDateTime(series.data_end)}
                </span>
              </>
            ) : null}
          </p>
        </div>
        <div className="lab-series__shape">
          {shape ? (
            <>
              <span className="pill pill--auto">{metricClassLabel(shape.metric_class)}</span>
              <span className="muted mono">置信度 {shape.confidence.toFixed(2)}</span>
              <span className="muted mono">一致性 {(shape.consistency * 100).toFixed(0)}%</span>
              <span className="muted">
                候选 {shape.candidates.map(detectorLabel).join(' / ')}
              </span>
            </>
          ) : (
            <span className="muted">没有可判定的窗口</span>
          )}
        </div>
      </div>

      {series.windows.length === 0 ? (
        <p className="muted">这个范围内不足一个窗口 —— 放宽时间范围或调小窗口点数。</p>
      ) : (
        <Collapse
          size="small"
          ghost
          items={[
            {
              key: 'windows',
              // 默认收起 —— 一屏可能有几十条序列，全展开就是几十张表格
              label: `窗口明细（${series.windows.length} 个窗口）`,
              children: (
                <Table<LabWindow>
                  size="small"
                  rowKey="index"
                  columns={WINDOW_COLUMNS}
                  dataSource={series.windows}
                  pagination={false}
                  scroll={{ x: 960 }}
                />
              ),
            },
          ]}
        />
      )}
    </section>
  )
}

