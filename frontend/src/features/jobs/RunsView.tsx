import { Select } from 'antd'
import type { RunSummary, SeriesEntry } from '../../api/types'

export interface RunsViewProps {
  runs: RunSummary[]
  selectedRunId: number | undefined
  onSelect: (runId: number) => void
  loading?: boolean
}

/**
 * 运行记录下拉的文案。
 *
 * 照搬旧 `platform.js` 的 `loadRuns`：
 *   `#${r.id} ${r.status} (${r.n_series} 序列 / ${r.n_alerts} 告警)`
 * 失败时追加 ` · ${r.error.slice(0, 40)}`。
 */
export function formatRunOption(run: RunSummary): string {
  const base = `#${run.id} ${run.status} (${run.n_series} 序列 / ${run.n_alerts} 告警)`
  return run.error ? `${base} · ${run.error.slice(0, 40)}` : base
}

/**
 * 运行记录下拉。
 *
 * 选哪一次运行 → 预览图与对比数据都跟着变（run_id 是查询参数）。
 */
export function RunsView({ runs, selectedRunId, onSelect, loading = false }: RunsViewProps) {
  return (
    <div className="runs-view">
      <label className="runs-view__label" htmlFor="runs-view-select">
        运行记录
      </label>
      <Select
        id="runs-view-select"
        className="runs-view__select"
        loading={loading}
        value={selectedRunId}
        placeholder="选择一次运行"
        onChange={(value) => onSelect(value as number)}
        options={runs.map((r) => ({ value: r.id, label: formatRunOption(r) }))}
        disabled={runs.length === 0}
        style={{ minWidth: 320 }}
      />
    </div>
  )
}

export interface SeriesSelectProps {
  series: SeriesEntry[]
  selectedSeriesId: string | undefined
  onSelect: (seriesId: string) => void
  loading?: boolean
}

/**
 * 序列下拉的文案。
 *
 * 照搬旧 `platform.js`：
 *   `${s.series_id} (${s.sufficient === false ? '数据不足' : `${s.n_alerts} 告警`})`
 *
 * ⚠️ 旧 UI **没有 P0 数**，P0 数是新增项（spec §8.2-C）—— 这一版先不加，别混淆。
 */
export function formatSeriesOption(series: SeriesEntry): string {
  const suffix = series.sufficient === false ? '数据不足' : `${series.n_alerts} 告警`
  return `${series.series_id} (${suffix})`
}

/** 序列下拉。选序列 → 预览图与对比数据都跟着变（series_id 是查询参数）。 */
export function SeriesSelect({
  series,
  selectedSeriesId,
  onSelect,
  loading = false,
}: SeriesSelectProps) {
  return (
    <div className="runs-view">
      <label className="runs-view__label" htmlFor="series-select">
        序列
      </label>
      <Select
        id="series-select"
        className="runs-view__select"
        loading={loading}
        value={selectedSeriesId}
        placeholder="选择序列"
        onChange={(value) => onSelect(value as string)}
        options={series.map((s) => ({ value: s.series_id, label: formatSeriesOption(s) }))}
        disabled={series.length === 0}
        style={{ minWidth: 320 }}
      />
    </div>
  )
}
