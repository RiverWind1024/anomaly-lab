/**
 * 「预览指标数据」页的地址构造。
 *
 * ⚠️ 单独抽出来是为了能单测 —— 地址里少带一个参数，
 *    预览页就退回默认 SQL，看起来像「预览坏了」。
 */

/** 预览页需要的全部参数。 */
export interface PreviewParams {
  /** 编辑已有指标时带上 —— 预览页据此提供「保存回指标」 */
  metricId?: number
  /** 数据源 id —— 必需，预览要在它上面跑查询 */
  sourceId?: number
  sql?: string
  time_column?: string
  value_column?: string
  group_column?: string
  time_format?: string
  source_timezone?: string
}

/** 预览页的路由。 */
export const PREVIEW_ROUTE = '/metric-preview'

/**
 * 拼预览页地址。
 *
 * ⚠️ 参数一律进 query —— 预览页在新标签页里打开，
 *    地址本身就是它唯一的输入。
 */
export function buildPreviewUrl(params: PreviewParams): string {
  const q = new URLSearchParams()
  if (params.metricId != null) q.set('metricId', String(params.metricId))
  if (params.sourceId != null) q.set('sourceId', String(params.sourceId))
  if (params.sql) q.set('sql', params.sql)
  if (params.time_column) q.set('time_column', params.time_column)
  if (params.value_column) q.set('value_column', params.value_column)
  if (params.group_column) q.set('group_column', params.group_column)
  if (params.time_format) q.set('time_format', params.time_format)
  if (params.source_timezone) q.set('source_timezone', params.source_timezone)
  return `${PREVIEW_ROUTE}?${q.toString()}`
}
