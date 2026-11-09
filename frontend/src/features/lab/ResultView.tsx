/** Lab 预检结果视图。 */
import { Alert } from 'antd'
import type { LabInspectResult } from '../../api/types'
import { metricClassLabel } from '../jobs/ClassificationCard'
import { SeriesPanel } from './SeriesPanel'

export function ResultView({ result }: { result: LabInspectResult }) {
  const totalWindows = result.series.reduce((sum, item) => sum + item.windows.length, 0)
  const sufficientWindows = result.series.reduce(
    (sum, item) => sum + item.windows.filter((window) => window.sufficient).length,
    0,
  )
  /**
   * 主形态 —— 按**窗口**投票，不是按序列投票。
   *
   * ⚠️ 序列数与窗口数不是一回事：分组指标有 20 条序列时，
   *    按序列投票会让某一条序列主导结论；按窗口投票才是数据的实况。
   */
  const classVotes = new Map<string, number>()
  result.series.forEach((item) => {
    item.windows.forEach((window) => {
      const key = window.classification?.metric_class
      if (key) classVotes.set(key, (classVotes.get(key) ?? 0) + 1)
    })
  })
  const dominantClass = [...classVotes.entries()].sort((a, b) => b[1] - a[1])[0]
  const dominantVotes = dominantClass ? dominantClass[1] : 0
  const dominantShare = dominantVotes && totalWindows ? dominantVotes / totalWindows : 0

  return (
    <>
      {result.warnings.map((warning) => (
        <Alert key={warning} type="warning" showIcon message={warning} />
      ))}

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">这次预检看到了什么</h2>
            <p className="panel__meta mono">
              {result.freq} · 每窗 {result.window_points} 点 · {result.sampling.mode}
            </p>
          </div>
        </div>
        <div className="lab-summary">
          <div className="lab-summary__item">
            <span className="lab-summary__k">序列</span>
            <span className="lab-summary__v mono">{result.series.length}</span>
          </div>
          <div className="lab-summary__item">
            <span className="lab-summary__k">采样窗口</span>
            <span className="lab-summary__v mono">{totalWindows}</span>
          </div>
          <div className="lab-summary__item">
            <span className="lab-summary__k">数据充足</span>
            <span className="lab-summary__v mono">
              {sufficientWindows} / {totalWindows}
            </span>
          </div>
          <div className="lab-summary__item">
            <span className="lab-summary__k">主形态</span>
            <span className="lab-summary__v">
              {dominantClass ? metricClassLabel(dominantClass[0]) : '—'}
            </span>
            <span className="lab-summary__s">
              {dominantClass ? `${dominantVotes} 个窗口 · ${(dominantShare * 100).toFixed(0)}%` : '—'}
            </span>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel__head">
          <div>
            <h2 className="panel__title">周期可识别性</h2>
          </div>
        </div>
        <table className="kvtable">
          <tbody>
            <tr>
              <th>日周期</th>
              <td>
                需要 {result.period_capability.daily_points} 点 ·{' '}
                {result.period_capability.daily_ok ? (
                  <span className="pill pill--ok">可识别</span>
                ) : (
                  <span className="pill pill--p1">看不到</span>
                )}
              </td>
            </tr>
            <tr>
              <th>周周期</th>
              <td>
                需要 {result.period_capability.weekly_points} 点 ·{' '}
                {result.period_capability.weekly_ok ? (
                  <span className="pill pill--ok">可识别</span>
                ) : (
                  <span className="pill pill--p1">看不到</span>
                )}
              </td>
            </tr>
            <tr>
              <th>可估计的最长周期</th>
              <td className="mono">{result.period_capability.max_period_points} 点</td>
            </tr>
          </tbody>
        </table>
      </section>

      {result.series.length === 0 ? (
        <section className="panel">
          <p className="muted">没有取到数据 —— 检查时间范围、查询条件与数据源连接。</p>
        </section>
      ) : (
        result.series.map((series) => <SeriesPanel key={series.series_id} series={series} />)
      )}
    </>
  )
}

