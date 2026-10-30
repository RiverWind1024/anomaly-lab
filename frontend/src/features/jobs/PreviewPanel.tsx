import { Alert, Button, Space, Tag } from 'antd'
import { StateBoundary } from '../../components/StateBoundary'
import type { Preview } from '../../api/types'
import { PreviewChart } from './PreviewChart'
import { formatRules } from './rules'

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
              <Tag>{p.detector}</Tag>
              <Tag>score_type: {p.score_type}</Tag>
              <Tag>{p.n_valid}/{p.n} 有效点</Tag>
              {p.n_missing > 0 && <Tag color="warning">{p.n_missing} 缺点</Tag>}
              {p.sampled && (
                <Tag color="processing">
                  已抽样 {p.n}/{p.original_n} 点
                </Tag>
              )}
            </Space>
            <span className="muted">规则 {formatRules(p.alert_rules)}</span>
          </div>

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
        </div>
      )}
    </StateBoundary>
  )
}
