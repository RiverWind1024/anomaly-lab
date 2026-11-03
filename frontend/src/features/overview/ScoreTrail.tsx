import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { fmtUtcTime } from '../../lib/format'
import { buildTrail, stripRect, type TrailGeometry } from './trail'
import type { AlertEvent, Preview, SeriesEntry } from '../../api/types'
import './overview.css'

/** 时间窗口（小时）；null = 本次运行的全部。 */
const WINDOWS: Array<{ key: string; label: string; hours: number | null }> = [
  { key: 'all', label: '本次运行', hours: null },
  { key: '24', label: '24h', hours: 24 },
  { key: '12', label: '12h', hours: 12 },
  { key: '6', label: '6h', hours: 6 },
]

export interface ScoreTrailProps {
  /** 当前序列的检测结果 */
  preview: Preview | undefined
  /** 当前序列的告警事件（画成条带） */
  events: AlertEvent[]
  /** 可切换的序列 */
  series: SeriesEntry[]
  activeSeries: string | undefined
  onSeriesChange: (seriesId: string) => void
  isLoading: boolean
  error: unknown
}

/** 量一下容器宽度 —— 轨迹要按宽度重算刻度。 */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  // ⚠️ 初始给一个宽度：jsdom 里量不到宽度（永远是 0），
  //    没有它图就永远画不出来。
  const [width, setWidth] = useState(900)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    const update = () => {
      if (node.clientWidth > 0) setWidth(node.clientWidth)
    }
    update()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', update)
      return () => window.removeEventListener('resize', update)
    }
    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return { ref, width }
}

/** 序列 ID 的短名：`demo-metric:web-api` → `web-api`。 */
function shortName(seriesId: string): string {
  const idx = seriesId.lastIndexOf(':')
  return idx >= 0 ? seriesId.slice(idx + 1) : seriesId
}

/**
 * 异常分数轨迹 —— 这个产品自己的那一个元素。
 *
 * 一条线（分数）、两条虚线（两档阈值）、两条条带（P0 / P1 事件），
 * 峰值标出来。颜色只给数据：主线是唯一的数据色，阈值与事件用状态色。
 */
export function ScoreTrail({
  preview,
  events,
  series,
  activeSeries,
  onSeriesChange,
  isLoading,
  error,
}: ScoreTrailProps) {
  const [windowKey, setWindowKey] = useState('all')
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null)
  const { ref, width } = useWidth<HTMLDivElement>()

  const hours = WINDOWS.find((w) => w.key === windowKey)?.hours ?? null

  const geom: TrailGeometry | null = useMemo(() => {
    if (!preview || !width) return null
    return buildTrail(preview.timestamps, preview.scores, preview.values, {
      width,
      height: 240,
      windowHours: hours,
      alertThreshold: preview.alert_threshold,
      criticalThreshold: preview.critical_threshold,
    })
  }, [preview, width, hours])

  const p1 = preview?.alert_threshold ?? 0
  const p0 = preview?.critical_threshold ?? 0

  return (
    <section className="panel" aria-labelledby="trailTitle">
      <div className="panel__head">
        <div>
          <h2 className="panel__title" id="trailTitle">
            异常分数轨迹
          </h2>
          <p className="panel__meta mono">
            {preview
              ? `${preview.series_id} · run ${preview.run_id} · ${preview.detector} / ${preview.score_type}`
              : '—'}
          </p>
        </div>
        <div className="seg" role="tablist" aria-label="时间窗口">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              type="button"
              role="tab"
              aria-selected={windowKey === w.key}
              onClick={() => setWindowKey(w.key)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <div className="seriesbar">
        <span className="seriesbar__k">序列</span>
        <div className="sery" role="tablist" aria-label="选择序列">
          {series.map((item) => (
            <button
              key={item.series_id}
              type="button"
              role="tab"
              aria-selected={item.series_id === activeSeries}
              title={`${item.series_id} · ${item.n_alerts} 个告警点`}
              onClick={() => onSeriesChange(item.series_id)}
            >
              <span className="mono">{shortName(item.series_id)}</span>
              <span className="sery__n mono">{item.n_alerts}</span>
            </button>
          ))}
        </div>
        <div className="legend" aria-hidden="true">
          <span className="legend__item">
            <i className="swatch swatch--line" />
            分数
          </span>
          <span className="legend__item">
            <i className="swatch swatch--p1" />
            P1 {p1}
          </span>
          <span className="legend__item">
            <i className="swatch swatch--p0" />
            P0 {p0}
          </span>
        </div>
      </div>

      <div className="trail__chart" ref={ref}>
        {error ? (
          <p className="trail__empty">轨迹加载失败</p>
        ) : !geom ? (
          <p className="trail__empty">
            {isLoading ? '加载中…' : '这个任务还没有检测结果'}
          </p>
        ) : (
          <svg            viewBox={`0 0 ${geom.padL + geom.plotW + geom.padR} 240`}
            width="100%"
            height="240"
            role="img"
            aria-label={`${preview?.series_id ?? ''} 异常分数轨迹：${geom.view.length} 个点，峰值 ${geom.peak?.s.toFixed(2) ?? '—'}σ，P1 阈值 ${p1}，P0 阈值 ${p0}`}
            onPointerLeave={() => setHover(null)}
          >
            {/* 横向网格 + y 轴刻度 */}
            {[0, 1, 2, 3].map((g) => {
              const value = (geom.yMax / 3) * g
              return (
                <g key={g}>
                  <line
                    x1={geom.padL}
                    x2={geom.padL + geom.plotW}
                    y1={geom.y(value)}
                    y2={geom.y(value)}
                    style={{ stroke: 'var(--border-subtle)', strokeWidth: 1, opacity: 0.55 }}
                  />
                  {g > 0 ? (
                    <text
                      x={geom.padL - 7}
                      y={geom.y(value)}
                      textAnchor="end"
                      dominantBaseline="middle"
                      style={{ fill: 'var(--text-tertiary)', fontSize: 12 }}
                    >
                      {Math.round(value)}
                    </text>
                  ) : null}
                </g>
              )
            })}

            {/* 基线 */}
            <line
              x1={geom.padL}
              x2={geom.padL + geom.plotW}
              y1={geom.plotBottom}
              y2={geom.plotBottom}
              style={{ stroke: 'var(--border-subtle)', strokeWidth: 1 }}
            />

            {/* 两条阈值：P0 更醒目 */}
            {[
              { v: p1, color: 'var(--status-p1)', name: 'P1' },
              { v: p0, color: 'var(--status-p0)', name: 'P0' },
            ].map((th) => (
              <g key={th.name}>
                <line
                  x1={geom.padL}
                  x2={geom.padL + geom.plotW}
                  y1={geom.y(th.v)}
                  y2={geom.y(th.v)}
                  style={{
                    stroke: th.color,
                    strokeWidth: 1,
                    strokeDasharray: '4 4',
                    strokeOpacity: 0.55,
                  }}
                />
                {geom.plotW >= 320 ? (
                  <text
                    x={geom.padL + geom.plotW - 2}
                    y={th.v === p0 ? Math.max(geom.padT + 12, geom.y(th.v) - 6) : geom.y(th.v) + 12}
                    textAnchor="end"
                    style={{ fill: th.color, fontSize: 12 }}
                  >
                    {th.name} {th.v}
                  </text>
                ) : null}
              </g>
            ))}

            {/* 曲线下的极淡底 + 曲线 */}
            <path d={geom.area} style={{ fill: 'var(--chart-fill)' }} />
            <path
              d={geom.path}
              style={{
                fill: 'none',
                stroke: 'var(--chart)',
                strokeWidth: 1.75,
                strokeLinejoin: 'round',
                strokeLinecap: 'round',
              }}
            />

            {/* 告警事件条带：P0 一行、P1 一行 */}
            <rect
              x={geom.padL}
              y={geom.p0RowY}
              width={geom.plotW}
              height={geom.stripH}
              rx={1}
              style={{ fill: 'var(--border-subtle)', opacity: 0.5 }}
            />
            <rect
              x={geom.padL}
              y={geom.p1RowY}
              width={geom.plotW}
              height={geom.stripH}
              rx={1}
              style={{ fill: 'var(--border-subtle)', opacity: 0.5 }}
            />
            {events.map((e) => {
              const rect = stripRect(geom, e.start_ts, e.end_ts)
              if (!rect) return null
              const isP0 = e.level_index >= 2
              return (
                <rect
                  key={`${e.job_id}-${e.series_id}-${e.start_ts}`}
                  x={rect.x}
                  y={isP0 ? geom.p0RowY : geom.p1RowY}
                  width={rect.width}
                  height={geom.stripH}
                  rx={1}
                  style={{ fill: isP0 ? 'var(--status-p0)' : 'var(--status-p1)' }}
                />
              )
            })}
            {geom.showStripLabels ? (
              <>
                <text
                  x={geom.padL - 7}
                  y={geom.p0RowY + geom.stripH - 1}
                  textAnchor="end"
                  style={{ fill: 'var(--status-p0)', fontSize: 12 }}
                >
                  P0
                </text>
                <text
                  x={geom.padL - 7}
                  y={geom.p1RowY + geom.stripH - 1}
                  textAnchor="end"
                  style={{ fill: 'var(--status-p1)', fontSize: 12 }}
                >
                  P1
                </text>
              </>
            ) : null}

            {/* 峰值标注 */}
            {geom.peak && geom.peak.s >= p1 ? (
              <g>
                <circle
                  cx={geom.x(geom.peak.t)}
                  cy={geom.y(geom.peak.s)}
                  r={3.2}
                  style={{ fill: 'var(--chart)', stroke: 'var(--surface-panel)', strokeWidth: 1.5 }}
                />
                <text
                  x={Math.min(
                    Math.max(geom.x(geom.peak.t), geom.padL + 40),
                    geom.padL + geom.plotW - 40,
                  )}
                  y={Math.max(geom.padT + 11, geom.y(geom.peak.s) - 9)}
                  textAnchor="middle"
                  style={{ fill: 'var(--text-primary)', fontSize: 12, fontWeight: 500 }}
                >
                  {geom.peak.s.toFixed(2)}σ
                  {geom.clipped ? ' ↑' : ''} ·{' '}
                  {fmtUtcTime(preview?.timestamps[geom.peak.i] ?? null)}
                </text>
              </g>
            ) : null}

            {/* x 轴刻度 */}
            {geom.ticks.map((t, i) => {
              const text = fmtUtcTime(new Date(t).toISOString())
              const label = geom.wideLabels ? text : text.slice(6)
              const half = label.length * 3.35
              let anchor: 'middle' | 'start' | 'end' = 'middle'
              if (i === 0 && geom.x(t) - half < 2) anchor = 'start'
              if (i === geom.ticks.length - 1 && geom.x(t) + half > geom.padL + geom.plotW) {
                anchor = 'end'
              }
              return (
                <text
                  key={t}
                  x={geom.x(t)}
                  y={236}
                  textAnchor={anchor}
                  style={{ fill: 'var(--text-tertiary)', fontSize: 12 }}
                >
                  {label}
                </text>
              )
            })}

            {/* 悬停：十字线 + 最近点 */}
            {hover ? (
              <g style={{ pointerEvents: 'none' }}>
                <line
                  x1={hover.x}
                  x2={hover.x}
                  y1={geom.padT}
                  y2={geom.plotBottom}
                  style={{
                    stroke: 'var(--text-tertiary)',
                    strokeWidth: 1,
                    strokeDasharray: '3 3',
                    strokeOpacity: 0.7,
                  }}
                />
                <circle
                  cx={hover.x}
                  cy={hover.y}
                  r={3}
                  style={{ fill: 'var(--chart)', stroke: 'var(--surface-panel)', strokeWidth: 1.5 }}
                />
              </g>
            ) : null}

            {/* 命中区 */}
            <rect
              x={geom.padL}
              y={geom.padT}
              width={geom.plotW}
              height={geom.plotH}
              fill="transparent"
              onPointerMove={(ev) => {
                const box = ev.currentTarget.ownerSVGElement?.getBoundingClientRect()
                if (!box) return
                const scale = (geom.padL + geom.plotW + geom.padR) / box.width
                const px = (ev.clientX - box.left) * scale
                const t = geom.vMin + ((px - geom.padL) / geom.plotW) * (geom.vMax - geom.vMin)
                let best = geom.view[0]
                for (const p of geom.view) {
                  if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p
                }
                setHover({
                  x: geom.x(best.t),
                  y: geom.y(best.s),
                  text: `${fmtUtcTime(preview?.timestamps[best.i] ?? null)} UTC · ${best.s.toFixed(2)}σ`,
                })
              }}
            />
          </svg>
        )}

        <div
          className="chart__tip"
          data-on={hover ? '1' : '0'}
          style={{ left: hover ? hover.x : 0 }}
          aria-hidden="true"
        >
          {hover ? <p>{hover.text}</p> : null}
        </div>
      </div>

      <div className="panel__foot">
        <span className="mono">
          {preview
            ? `${preview.n_alerts} 个告警点 · ${preview.n_p0} 个 P0 点`
            : '—'}
        </span>
        <span className="mono">
          {preview ? `更新于 ${fmtUtcTime(preview.timestamps[preview.timestamps.length - 1])} UTC` : '—'}
        </span>
      </div>
    </section>
  )
}

/** 序列切换 + 图表需要的辅助链接（评估报告）。 */
export function TrailLink() {
  return (
    <Link className="link" to="/evaluation">
      评估报告
    </Link>
  )
}
