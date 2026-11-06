import { Alert, Button, Space, Tag } from 'antd'
import { StateBoundary } from '../../components/StateBoundary'
import type { Preview } from '../../api/types'
import { AlertRulesView } from './AlertRulesView'
import { ScaleStatusTags } from './ScaleStatusTags'
import { detectorLabel } from '../../lib/detectorLabels'
import { DetectionConclusion } from './ClassificationCard'
import { PreviewChart } from './PreviewChart'
import { DecisionTraceTimeline } from '../evaluation/DecisionTraceTimeline'

export interface PreviewPanelProps {
  isLoading: boolean
  error: unknown
  preview: Preview | undefined
  onRun: () => void
  running?: boolean
}

/**
 * 预览面板：图表 + 抽样提示 + 数据状态。
 *
 * ⚠️ **数据不足是 200 + `sufficient:false`**，不是 404 ——
 *    所以要走 StateBoundary 的 `insufficient` 回调，不能靠 error 判断。
 */
export function PreviewPanel({ isLoading, error, preview, onRun, running = false }: PreviewPanelProps) {
  return (
    <StateBoundary
      isLoading={isLoading}
      error={error}
      data={preview}
      insufficient={(p) =>
        p.sufficient ? null : p.insufficient_reason || '有效点不足，不足以做检测'
      }
      bizTitles={{ no_run: '该任务还没有运行记录' }}
      emptyAction={
        <Button type="primary" loading={running} onClick={onRun}>
          立即运行
        </Button>
      }
    >
      {(p) => (
        <div className="preview-panel">
          <div className="preview-panel__meta">
            <Space size="small" wrap>
              <Tag>{detectorLabel(p.detector)}</Tag>
              <Tag>score_type: {p.score_type}</Tag>
              <ScaleStatusTags
                status={p.status}
                scaleSource={p.scale_source}
                scaleFallback={p.scale_fallback}
              />
              <Tag>{p.n_valid}/{p.n} 有效点</Tag>
              {p.n_missing > 0 && <Tag color="warning">{p.n_missing} 缺点</Tag>}
              {p.sampled && (
                <Tag color="processing">
                  已抽样 {p.n}/{p.original_n} 点
                </Tag>
              )}
            </Space>
          </div>

          {/* 方向没生效：告警数 0 不代表数据正常，必须明说 */}
          {p.direction_applied === false ? (
            <Alert
              type="warning"
              showIcon
              message="这个任务的算法没有基线，无法判断「只报偏低」"
              description="本次运行没有产生告警，不代表数据正常。请把告警方向改成「双向」，或换一个支持基线的算法。"
              style={{ marginBottom: 12 }}
            />
          ) : null}

          {/* 检测结论：形态 / 回退 / score_type / 推荐理由（旧 UI 的 hint 主体） */}
          <DetectionConclusion
            requestedDetector={p.requested_detector}
            detector={p.detector}
            metricClass={p.metric_class}
            fallback={p.detector_fallback}
            scoreType={p.score_type}
            rationale={p.detector_rationale}
          />

          <AlertRulesView rules={p.alert_rules} />

          {p.sampled && (
            <Alert
              type="info"
              showIcon
              message={`点数过多，已抽样显示 ${p.n}/${p.original_n} 点`}
              description="抽样只影响显示，不影响告警判定 —— 告警数是全量计算的。"
              style={{ marginBottom: 12 }}
            />
          )}

          <PreviewChart
            timestamps={p.timestamps}
            values={p.values}
            scores={p.scores}
            baseline={p.baseline}
            lower={p.lower}
            upper={p.upper}
            severity={p.severity}
            alertThreshold={p.alert_threshold}
            criticalThreshold={p.critical_threshold}
            levels={p.levels}
          />

          {/* 决策链：数据质量 → 能力探测 → 形态判断 → 算法选择 → 阈值与分级 → 结果 */}
          {p.decision && Object.keys(p.decision).length > 0 ? (
            <section className="preview-panel__trace">
              <h3 className="preview-panel__trace-title">检测流程</h3>
              <p className="preview-panel__trace-hint">
                这次为什么这么判 —— 每一步的结论与原始数字都在这里
              </p>
              <DecisionTraceTimeline trace={p.decision} />
            </section>
          ) : null}
        </div>
      )}
    </StateBoundary>
  )
}
