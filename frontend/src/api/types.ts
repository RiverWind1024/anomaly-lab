/**
 * 后端 API 的手写类型。
 *
 * ⚠️ **字段名不许改** —— 全部照后端实际响应逐字段核对（2026-10-30 实测）。
 *    后端改字段时这里必须同步改，否则运行期才发现，代价很高。
 *
 * 核对来源：
 *   - /api/platform/* → 运行中的后端实测响应
 *   - /api/summary、/api/badcases、/api/annotate → 端点源码 + 实测
 *   - 评估 rows/summary → reports/latest/report.json
 *
 * 类型按域拆在 `types/` 下，这里只做聚合导出 —— 调用方仍从 `api/types` 导入。
 */

export * from './types/common'
export * from './types/sources'
export * from './types/alerts'
export * from './types/jobs'
export * from './types/feedback'
export * from './types/evaluation'
export * from './types/lab'
export * from './types/observability'
