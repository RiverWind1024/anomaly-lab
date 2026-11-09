/** 归档数据集与归档记录。 */

export interface ArchiveSet {
  id: number
  name: string
  description: string
  created_at: string
  /** 数据集里有多少条归档记录。 */
  n_records: number
}

/**
 * 一条归档记录 —— 是检测记录的**独立副本**。
 *
 * ⚠️ 原检测记录被删除 / 被保留策略清理后，这里仍然可查看。
 */
export interface ArchiveRecord {
  id: number
  archive_set_id: number
  run_id: number
  series_id: string
  group_name: string | null
  job_name: string
  metric_name: string
  detector: string
  n: number
  n_valid: number
  n_alerts: number
  n_p0: number
  start_ts: string
  end_ts: string
  /** 归档时填写的说明 / 原因。 */
  description: string
  /** 归档副本相对 data_root 的路径。 */
  file: string
  decision_json: string
  content_hash: string
  archived_at: string
}
