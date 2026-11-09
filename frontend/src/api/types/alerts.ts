/** API 类型：告警记录 / 概览 / 存储与保留。 */
// ─────────────────────────────────────────── 告警记录 /api/platform/alerts

/**
 * 一条告警事件 = 一段连续告警点合并成的区间。
 *
 * ⚠️ `level` 是**档位名**，来自任务的规则表，不一定是 P0/P1（可自定义如「注意」）。
 *    `level_index` 才是严重度序（越大越严重）—— 排序、筛选用它。
 */
export interface AlertEvent {
  job_id: number
  job_name: string
  metric_id: number
  metric_name: string
  series_id: string
  group: string | null
  level: string
  level_index: number
  start_ts: string
  end_ts: string
  n_points: number
  max_score: number
  detector: string
  score_type: string
  run_id: number
}

/** 没被纳入统计的任务 —— 必须说清为什么，不能静默消失。 */
export interface SkippedJob {
  job_id: number
  name: string
  reason: string
}

// ─────────────────────────────────────────── 概览 /api/platform/overview

export interface OverviewCounts {
  sources: number
  metrics: number
  jobs: number
  enabled_jobs: number
}

export interface OverviewRuns {
  total: number
  success: number
  failed: number
  running: number
}

export interface OverviewLatestRun {
  id: number
  status: string
  started_at: string
  finished_at: string | null
  n_series: number
  n_alerts: number
  error: string | null
}

export interface OverviewJob {
  id: number
  name: string
  enabled: boolean
  detector: string
  metric_id: number
  last_run: OverviewLatestRun | null
}

export interface Overview {
  counts: OverviewCounts
  runs: OverviewRuns
  alerts: {
    total: number
    by_level: Array<{ level: string; count: number }>
    by_job: Array<{ job_id: number; job_name: string; count: number }>
    top_series: Array<{ series_id: string; count: number }>
    /** 没纳入统计的任务数（没跑过 / 失败 / 运行中）。 */
    skipped: number
  }
  feedback: {
    total: number
    by_kind: Array<{ kind: string; count: number }>
  }
  jobs: OverviewJob[]
}

// ─────────────────────────────────────────── 存储与保留 /api/platform/storage

/** 保留策略 —— 只有一个维度：保留多少天。 */
export interface RetentionPolicyInfo {
  retention_days: number
}

export interface StorageUsage {
  policy: RetentionPolicyInfo
  runs: {
    /** 保留中的运行记录数。 */
    kept: number
    /** 结果目录数。 */
    n_dirs: number
    /** 结果目录占用的字节数。 */
    bytes: number
  }
  database: {
    path: string
    bytes: number
  }
  feedback: {
    total: number
  }
  /** 上次清理时间；还没清过是 null。 */
  last_pruned_at: string | null
  last_pruned: {
    deleted_runs: number
    freed_bytes: number
  }
}

/** 一次清理的结果。 */
export interface PruneResult {
  deleted_runs: number
  deleted_dirs: number
  orphan_dirs: number
  freed_bytes: number
  kept_runs: number
  dry_run: boolean
  /**
   * 触发了磁盘上限兜底的任务 —— 它们的实际保留期比配置的短。
   *
   * ⚠️ 保留期永远优先，但任务频率太高时磁盘会撑不住，
   *    这时候宁可少留也不能让平台崩掉。触发了要让人知道。
   */
  disk_capped_jobs: number[]
  /** 清理后的最新占用 —— 少发一次请求。 */
  storage?: StorageUsage
}

export interface AlertListResponse {
  events: AlertEvent[]
  levels: string[]
  /** 序列候选 —— 来自**未筛选**的集合，否则筛选器会把自己锁死。 */
  series: string[]
  jobs: { id: number; name: string }[]
  skipped: SkippedJob[]
}

