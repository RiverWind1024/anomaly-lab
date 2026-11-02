/**
 * 预览页 → 指标表单 的回传通道。
 *
 * ⚠️ 为什么不用 postMessage：那个要靠 `window.opener`，
 *    而 opener 会被浏览器的隐私设置、`rel="noreferrer"` 之类切断 ——
 *    断了就静默失败，用户看不出为什么配置没回来。
 *    localStorage 是同源共享的，任何标签页都收得到。
 *
 * ⚠️ storage 事件只在**别的**标签页触发 —— 正好符合这里的需求
 *    （写的是预览页，收的是原页面）。
 */

/** localStorage 的键。 */
export const PREVIEW_STORAGE_KEY = 'anomaly-lab:metric-preview'

/** 回传的配置。 */
export interface PreviewPayload {
  sourceId: number
  sql: string
  columns: Array<{ name: string; type: string }>
  time_column?: string
  value_column?: string
  group_column?: string
  time_format?: string
}

/** 超过这个时间的回传不再采纳 —— 别把上次留下的配置填进今天的表单。 */
const MAX_AGE_MS = 5 * 60 * 1000

/** 写回传配置（预览页调）。 */
export function writePreviewPayload(payload: PreviewPayload): void {
  try {
    window.localStorage.setItem(
      PREVIEW_STORAGE_KEY,
      JSON.stringify({ payload, at: Date.now() }),
    )
  } catch {
    // ⚠️ 隐私模式下 localStorage 可能写不了 —— 这时只能靠复制 SQL 兜底
  }
}

/**
 * 读回传配置（表单所在页面调）。
 *
 * @param raw localStorage 里的原始字符串
 * @returns 有效且未过期的配置；否则 null
 */
export function readPreviewPayload(raw: string | null): PreviewPayload | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as { payload?: PreviewPayload; at?: number }
    if (!parsed.payload || typeof parsed.at !== 'number') return null
    if (Date.now() - parsed.at > MAX_AGE_MS) return null
    return parsed.payload
  } catch {
    return null
  }
}
