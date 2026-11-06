import { useState } from 'react'
import { Alert } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ClassificationCard } from '../../features/jobs/ClassificationCard'
import { CompareChart } from '../../features/jobs/CompareChart'
import { ComparePicker } from '../../features/jobs/ComparePicker'
import { CompareTable } from '../../features/jobs/CompareTable'
import { PreviewPanel } from '../../features/jobs/PreviewPanel'
import { RunsView, SeriesSelect } from '../../features/jobs/RunsView'
import { useCompare, usePreview, useRuns, useToggleJob } from '../../features/jobs/queries'
import type { CatalogDetector } from '../../api/types'

export interface JobDetectionsPanelProps {
  jobId: number
  runId?: number
  detectors: CatalogDetector[]
  enabled: boolean
}

/**
 * 检测结果面板：预览图 + 多算法对比 + 分类结论。
 *
 * 之前这些都挤在详情页里，和配置表单混在一起 ——
 * 现在独立成页，一屏只讲「检测出了什么」。
 */
export function JobDetectionsPanel({
  jobId,
  runId,
  detectors,
  enabled,
}: JobDetectionsPanelProps) {
  const navigate = useNavigate()
  const [seriesId, setSeriesId] = useState<string | undefined>(undefined)
  const [selectedDetectors, setSelectedDetectors] = useState<string[]>([])

  const runs = useRuns(jobId, enabled)
  const preview = usePreview(jobId, runId, seriesId, enabled)
  const compare = useCompare(jobId, seriesId, selectedDetectors, enabled)
  const toggleJob = useToggleJob()

  const handleApplyDetector = (name: string) => {
    toggleJob.mutate(
      { jobId, payload: { detector: name } },
      {
        onSuccess: () => undefined,
        onError: () => undefined,
      },
    )
  }

  return (
    <div className="job-detections">
      <div className="runs-view__bar">
        {/* ⚠️ 运行下拉是「检测结果」的时间轴入口 ——
            没有它，用户只能看到最近一次运行，历史运行等于不存在。 */}
        <RunsView
          runs={runs.data?.runs ?? []}
          selectedRunId={runId}
          onSelect={(nextRunId) => {
            setSeriesId(undefined)
            navigate(`/jobs/${jobId}/detections?run_id=${nextRunId}`)
          }}
          loading={runs.isPending}
        />
        <SeriesSelect
          series={preview.data?.series ?? []}
          selectedSeriesId={seriesId ?? preview.data?.series_id}
          onSelect={setSeriesId}
          loading={preview.isPending}
        />
      </div>

      <PreviewPanel
        isLoading={preview.isPending}
        error={preview.error}
        preview={preview.data}
        onRun={() => undefined}
        running={false}
      />

      <section className="compare-section">
        <h2 className="section__title">多算法对比</h2>
        <ComparePicker
          available={compare.data?.available ?? []}
          fallbackNames={detectors.map((d) => d.name)}
          autoDetector={compare.data?.auto_detector ?? 'auto'}
          selected={selectedDetectors}
          onChange={setSelectedDetectors}
          detectors={detectors}
        />

        {/* 被跳过的算法：当前环境不可用（如缺 chronos 依赖/权重） */}
        {(compare.data?.skipped ?? []).map((item) => (
          <Alert
            key={item.name}
            type="warning"
            showIcon
            message={`${item.name} 已跳过`}
            description={item.reason}
            style={{ marginBottom: 12 }}
          />
        ))}

        {compare.data && (
          <>
            <ClassificationCard
              metricClass={compare.data.metric_class ?? ''}
              confidence={compare.data.confidence ?? 0}
              reasons={compare.data.reasons}
              autoDetector={compare.data.auto_detector}
              autoRationale={compare.data.auto_rationale}
              autoFallback={compare.data.auto_fallback}
              /* 分数类型要取 **auto 选中的那个算法** 的 ——
                 卡片讲的是 auto 推荐，不能拿 detectors[0] 的（顺序不保证是 auto）。 */
              scoreType={
                compare.data.detectors.find((d) => d.is_auto)?.score_type ??
                compare.data.detectors[0]?.score_type ??
                ''
              }
            />
            <CompareChart
              timestamps={compare.data.timestamps}
              values={compare.data.values}
              detectors={compare.data.detectors}
            />
            <CompareTable
              detectors={compare.data.detectors}
              levels={compare.data.levels}
              applyingDetector={
                toggleJob.isPending ? toggleJob.variables?.payload.detector ?? null : null
              }
              onApplyDetector={handleApplyDetector}
            />
          </>
        )}
      </section>
    </div>
  )
}
