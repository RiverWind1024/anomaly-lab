/** API 类型：服务监控（/api/platform/observability）。 */
// ───────────────────────────── 服务监控 /api/platform/observability

/** 一分钟的增量快照。 */
export interface ObservabilityPoint {
  at: string
  requests: number
  errors: number
  runs: number
  failed_runs: number
  insufficient_runs: number
  alerts: number
  p0: number
  p50_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
  cpu_percent: number | null
  memory_mb: number | null
  db_bytes: number | null
  runs_bytes: number | null
  runs_count: number | null
}

export interface ObservabilityRouteRow {
  method: string
  route: string
  count: number
  errors: number
  avg_ms: number | null
  p95_ms: number | null
}

export interface ObservabilityDetectorRow {
  detector: string
  calls: number
  fallbacks: number
  errors: number
  avg_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
}

export interface ObservabilityJobRow {
  job: string
  runs: number
  failed: number
  insufficient: number
  avg_ms: number | null
  p95_ms: number | null
}

export interface ObservabilityStageRow {
  stage: string
  count: number
  avg_ms: number | null
  p95_ms: number | null
}

export interface Observability {
  service: {
    service_name: string
    pid: number
    started_at: string
    uptime_seconds: number
    otel_enabled: boolean
    otel_endpoint: string
    sampler_running: boolean
    snapshot_at: string | null
  }
  interval_seconds: number
  current: {
    cpu_percent: number | null
    memory_mb: number | null
    db_bytes: number | null
    runs_bytes: number | null
    runs_count: number | null
    inflight: number
    due_jobs: number | null
  }
  timeline: ObservabilityPoint[]
  http: {
    total: number
    errors: number
    routes: ObservabilityRouteRow[]
  }
  /** 告警区间的累计数（不是最近 N 分钟的窗口）。 */
  alerts: {
    total: number
    p0: number
  }
  detectors: ObservabilityDetectorRow[]
  jobs: ObservabilityJobRow[]
  stages: ObservabilityStageRow[]
  scheduler: {
    alive: boolean
    ticks: number
    avg_tick_ms: number | null
    p95_tick_ms: number | null
    due_jobs: number | null
    last_tick_at: string | null
    avg_prune_ms: number | null
  }
  otel: {
    enabled: boolean
    endpoint: string
    hint: string
  }
}
