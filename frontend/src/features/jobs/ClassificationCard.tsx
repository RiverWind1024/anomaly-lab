import type { ReactNode } from 'react'
import { Card, Space, Tag, Tooltip } from 'antd'

export interface ClassificationCardProps {
  metricClass: string
  confidence: number
  reasons: string[]
  autoDetector: string
  autoRationale: string
  autoFallback: boolean
  scoreType: string
}

/**
 * 形态分类名 → 中文标签。
 *
 * 取值来自后端 `contracts.MetricClass`（6 种）。
 * 未登记的值原样显示 —— 宁可显示原始标识，也不要显示错的翻译。
 */
export const METRIC_CLASS_LABELS: Record<string, string> = {
  stationary: '平稳型',
  periodic: '周期型',
  trending: '趋势型',
  step: '阶梯型',
  high_zero_ratio: '高零值比例型',
  sparse_event: '稀疏事件型',
}

export function metricClassLabel(metricClass: string | null | undefined): string {
  if (!metricClass) return '未判定'
  return METRIC_CLASS_LABELS[metricClass] ?? metricClass
}

/**
 * 形态判定卡。
 *
 * 这是旧 UI 那句 `自动 → 检测器 · 形态（回退）· score_type · 规则` 的正式化
 * （spec §8.2-A）—— 把「为什么选这个算法」讲清楚，而不是只丢一个算法名。
 */
export function ClassificationCard({
  metricClass,
  confidence,
  reasons,
  autoDetector,
  autoRationale,
  autoFallback,
  scoreType,
}: ClassificationCardProps) {
  return (
    <Card size="small" className="classification-card" variant="outlined">
      {/* 用 CSS grid 而不是 AntD Descriptions 的响应式列 ——
          Descriptions 按**窗口**宽度算断点，但卡片在侧边栏右边，
          实际可用宽度更窄，会出现「4 项里最后 1 项单独折行」的尴尬布局。 */}
      <div className="classification-card__fields">
        <Field label="形态">
          <Space size="small">
            <strong>{metricClassLabel(metricClass)}</strong>
            <span className="muted mono">{metricClass || '—'}</span>
          </Space>
        </Field>
        <Field label="置信度">
          <span className="mono">{confidence.toFixed(2)}</span>
        </Field>
        <Field label="自动选用">
          <Space size="small">
            <span className="mono">{autoDetector}</span>
            {autoFallback && <Tag color="warning">回退</Tag>}
          </Space>
        </Field>
        <Field label="分数类型">
          <span className="mono">{scoreType || '—'}</span>
        </Field>
      </div>

      {reasons.length > 0 && (
        <div className="classification-card__reasons">
          <p className="classification-card__label">判定依据</p>
          <ul>
            {reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {autoRationale && (
        <div className="classification-card__rationale">
          <p className="classification-card__label">推荐理由</p>
          <p>{autoRationale}</p>
        </div>
      )}
    </Card>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="classification-card__field">
      <span className="classification-card__field-label">{label}</span>
      <span className="classification-card__field-value">{children}</span>
    </div>
  )
}

/**
 * 检测结论（一行）—— 预览面板用。
 *
 * 对应旧 UI 的 hint 主体：`自动 → 检测器 · 形态（回退）· score_type`。
 */
export function DetectionConclusion({
  requestedDetector,
  detector,
  metricClass,
  fallback,
  scoreType,
  rationale,
}: {
  requestedDetector: string
  detector: string
  metricClass: string
  fallback: boolean
  scoreType: string
  rationale: string
}) {
  const isAuto = requestedDetector === 'auto'
  return (
    <p className="detection-conclusion">
      {isAuto ? (
        <>
          自动 → <span className="mono">{detector}</span>
        </>
      ) : (
        <span className="mono">{detector}</span>
      )}
      {' · 形态 '}
      {metricClassLabel(metricClass)}
      {fallback && <span className="detection-conclusion__fallback">（回退）</span>}
      {' · score_type '}
      <span className="mono">{scoreType || '—'}</span>
      {rationale && (
        <Tooltip title={rationale}>
          <span className="muted detection-conclusion__why">为什么</span>
        </Tooltip>
      )}
    </p>
  )
}
