import type { AlertRule } from '../../api/types'

/**
 * 告警规则的解析与格式化。
 *
 * 照搬旧 `platform.js` 的 `parseRules` / `formatRules` 语义，
 * 但**把 alert() 换成行内错误** —— 旧版弹窗会打断输入（spec §8.2-B）。
 *
 * 规则语义（照搬旧 `platform.html` 的说明）：
 *   - **从上到下按严重程度排列**（最后一行最严重）
 *   - 命中多条时取最高档
 *   - 留空则用默认两档
 */

/** 绝对值条件：>50 / >= 50 / <10 / <= 10 */
const ABSOLUTE_RE = /^(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$/

export interface ParsedRules {
  rules: AlertRule[] | null
  /** 每行一条错误信息；key 是行号（从 1 开始） */
  errors: Record<number, string>
}

export function parseRules(text: string): ParsedRules {
  const rules: AlertRule[] = []
  const errors: Record<number, string> = {}

  const lines = String(text ?? '').split('\n')
  lines.forEach((line, index) => {
    const lineNo = index + 1
    const trimmed = line.trim()
    if (!trimmed) return

    const [expr, ...rest] = trimmed.split(',')
    // 行内逗号后的部分拼回等级（沿用旧 platform.js 的 rest.join(',') 行为）
    const level = rest.join(',').trim()
    if (!level) {
      errors[lineNo] = `第 ${lineNo} 行：缺少等级（应为「倍数, 等级」或「>50, 等级」）`
      return
    }

    const condition = expr.trim()
    const absolute = condition.match(ABSOLUTE_RE)
    if (absolute) {
      rules.push({ op: absolute[1], value: Number(absolute[2]), level })
      return
    }

    const value = Number(condition)
    if (!Number.isFinite(value)) {
      errors[lineNo] = `第 ${lineNo} 行：格式应为「倍数, 等级」或「>50, 等级」`
      return
    }
    // 倍数必须为正 —— 后端 parse_rules 会拒，前端当场拦下给行内错误
    if (value <= 0) {
      errors[lineNo] = `第 ${lineNo} 行：倍数必须大于 0`
      return
    }
    rules.push({ multiplier: value, level })
  })

  // 有错就整体不提交 —— 静默丢弃非法行会让用户以为规则生效了
  if (Object.keys(errors).length > 0) return { rules: null, errors }
  return { rules: rules.length ? rules : null, errors }
}

export function formatRules(rules: AlertRule[] | null | undefined): string {
  if (!rules?.length) return '-'
  return rules
    .map(
      (r) =>
        (r.multiplier == null ? `${r.op}${r.value}` : `${r.multiplier}×`) + `→${r.level}`,
    )
    .join(' / ')
}

/** 把规则数组转回输入框的纯文本（编辑既有任务时用）。 */
export function rulesToText(rules: AlertRule[] | null | undefined): string {
  if (!rules?.length) return ''
  return rules
    .map((r) => (r.multiplier == null ? `${r.op} ${r.value}` : `${r.multiplier}`) + `, ${r.level}`)
    .join('\n')
}

/**
 * 选算法时自动预填默认规则。
 *
 * 照搬旧 `platform.js`：默认阈值 × 1.5 作为 P0 档。
 */
export function defaultRulesFor(defaultThreshold: number): string {
  return `${defaultThreshold}, P1\n${(defaultThreshold * 1.5).toFixed(2)}, P0`
}
