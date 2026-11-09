/** 单条检测记录的详情：决策链 + 波形 + 关键指标。
 *
 * 平台运行记录与归档副本共用 —— 两边的数据形状完全一致，只是来源不同。
 */
import { Card, Space } from 'antd'
import type { RunSeriesDetail } from '../../api/types'
import { fmtMetric } from '../../lib/format'
import { detectorLabel } from '../../lib/detectorLabels'
import { DecisionTraceTimeline } from '../evaluation/DecisionTraceTimeline'
import { PreviewChart } from '../jobs/PreviewChart'
import { ScaleStatusTags } from '../jobs/ScaleStatusTags'

/** 空数组 → null：`PreviewChart` 用「有没有带」决定画不画带。 */
export function bandOf(values: number[] | undefined): (number | null)[] | null {
  return values && values.length > 0 ? values : null
}

export function SeriesRecordDetail({ data }: { data: RunSeriesDetail }) {
  return (
    <div className="platform-record">
      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">检测流程</h2>
            <p className="panel__meta">
              数据质量 → 能力探测 → 形态判断 → 算法选择 → 阈值与分级 → 结果
            </p>
          </div>
          <Space size="small" wrap>
            <ScaleStatusTags
              status={data.status}
              scaleSource={data.scale_source}
              scaleFallback={data.scale_fallback}
            />
          </Space>
        </div>
        <DecisionTraceTimeline trace={data.decision ?? {}} />
      </section>

      <Card size="small" title="波形与分数" className="platform-record__chart">
        <PreviewChart
          timestamps={data.timestamps}
          values={data.values}
          scores={data.scores}
          baseline={bandOf(data.baseline)}
          lower={bandOf(data.lower)}
          upper={bandOf(data.upper)}
          severity={data.severity}
          alertThreshold={data.alert_threshold ?? 0}
          criticalThreshold={data.critical_threshold ?? 0}
          levels={data.levels ?? ['正常']}
        />
      </Card>

      <table className="kvtable">
        <tbody>
          <tr>
            <th>检测器</th>
            <td>{detectorLabel(data.detector)}</td>
            <th>点数</th>
            <td className="mono">{data.values.length}</td>
          </tr>
          <tr>
            <th>告警点</th>
            <td className="mono">{data.severity.filter((level) => level > 0).length}</td>
            <th>P0 点</th>
            <td className="mono">{data.severity.filter((level) => level >= 2).length}</td>
          </tr>
          <tr>
            <th>尺度</th>
            <td className="mono">{data.scale_source || '—'}</td>
            <th>阈值</th>
            <td className="mono">{fmtMetric(data.alert_threshold ?? 0)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}
