import { useState } from 'react'
import { useSeries } from '../features/series/queries'
import { SeriesDetailDrawer } from '../features/series/SeriesDetailDrawer'
import { SeriesOverview } from '../features/series/SeriesOverview'
import type { SeriesMeta } from '../api/types'

/** 序列总览页。薄壳 —— 只负责取数与传参。 */
export function SeriesOverviewPage() {
  const { data, isPending, error } = useSeries()
  const [selected, setSelected] = useState<SeriesMeta | null>(null)

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">序列总览</h1>
        <p className="page__subtitle">
          {data ? `共 ${data.length} 条序列` : '加载中…'}
        </p>
      </header>
      <SeriesOverview
        isLoading={isPending}
        error={error}
        series={data}
        onOpenSeries={(seriesId) =>
          setSelected(data?.find((item) => item.series_id === seriesId) ?? null)
        }
      />
      <SeriesDetailDrawer series={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
