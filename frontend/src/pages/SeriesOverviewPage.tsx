import { useSeries } from '../features/series/queries'
import { SeriesOverview } from '../features/series/SeriesOverview'

/** 序列总览页。薄壳 —— 只负责取数与传参。 */
export function SeriesOverviewPage() {
  const { data, isPending, error } = useSeries()

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">序列总览</h1>
        <p className="page__subtitle">
          {data ? `共 ${data.length} 条序列` : '加载中…'}
        </p>
      </header>
      <SeriesOverview isLoading={isPending} error={error} series={data} />
    </div>
  )
}
