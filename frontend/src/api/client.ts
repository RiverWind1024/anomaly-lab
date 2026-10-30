/** 后端用这个响应头区分「业务态」（空/数据不足）与「真错误」。 */
export type BizState =
  | 'no_run'
  | 'no_series'
  | 'no_data'
  | 'insufficient_data'
  | 'no_algorithms'
  | 'no_result'

export class ApiError extends Error {
  readonly status: number
  readonly bizState?: BizState
  constructor(status: number, message: string, bizState?: BizState) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.bizState = bizState
  }
}

/**
 * 响应头缺失时的兜底：按 detail **前缀**判定业务态。
 *
 * 为什么要兜底：老版本后端（或任何没加头的 404）不该一律显示成红色错误框 ——
 * 「该任务还没有运行记录」是业务态（spec §6.1）。
 *
 * 前缀表与 spec §4.2.1 的 detail 列一一对应。
 * 后端改文案时**这里要同步改**，否则会退化成红框。
 */
const DETAIL_PREFIX_TO_STATE: ReadonlyArray<[string, BizState]> = [
  ['该任务还没有运行记录', 'no_run'],
  ['该次运行没有序列结果', 'no_series'],
  ['该窗口内没有取到数据', 'no_data'],
  ['有效点仅', 'insufficient_data'],
  ['没有可对比的算法', 'no_algorithms'],
  ['该序列还没有检测结果', 'no_result'],
]

function stateFromDetail(detail: string): BizState | undefined {
  for (const [prefix, state] of DETAIL_PREFIX_TO_STATE) {
    if (detail.includes(prefix)) return state
  }
  return undefined
}

/** FastAPI 的 422 把 detail 返成数组 [{loc, msg, type}]，直接渲染会得到 [object Object]。 */
function normalizeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : ''))
      .filter(Boolean)
    if (parts.length) return parts.join('；')
  }
  return '请求失败'
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  override?: Response,
): Promise<T> {
  const resp = override ?? (await fetch(path, init))
  if (!resp.ok) {
    let detail: unknown = resp.statusText
    try {
      const body = await resp.json()
      detail = (body as { detail?: unknown }).detail ?? detail
    } catch {
      /* 非 JSON 响应，保留 statusText */
    }
    const bizState = (resp.headers.get('X-Anomaly-Biz-State') as BizState | null)
      ?? stateFromDetail(normalizeDetail(detail))
    throw new ApiError(resp.status, normalizeDetail(detail), bizState ?? undefined)
  }
  return (await resp.json()) as T
}

export function postJson<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
