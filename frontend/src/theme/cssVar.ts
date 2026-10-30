/**
 * 从 CSS 变量读出实际色值。
 *
 * ⚠️ **ECharts 不能吃 CSS 变量** —— 它要做颜色运算（渐变、alpha 叠加），
 *    `var(--status-p0)` 传进去会得到错误颜色。所以必须运行时读出实际值。
 *
 * 与 `theme/antdTheme.ts` 的 `readToken` 同理，但**这里要带缓存**：
 * 图表 option 每次渲染都会重建，每次都读 getComputedStyle 太浪费。
 * 缓存 key 带上主题，主题切换时失效。
 */

const cache = new Map<string, string>()
let cachedTheme: string | null = null

function currentTheme(): string {
  if (typeof document === 'undefined') return 'none'
  return document.documentElement.getAttribute('data-theme') ?? 'none'
}

/** 主题变了就清缓存 —— 否则切主题后图表还是旧颜色。 */
function ensureThemeFresh(): void {
  const theme = currentTheme()
  if (theme !== cachedTheme) {
    cache.clear()
    cachedTheme = theme
  }
}

/**
 * 手动清空色值缓存。
 *
 * @param theme 传入已知的新主题时，缓存 key 会按它分桶 —— 同一主题下多次
 *              读取仍走缓存，换主题则一定读到新值。
 */
export function invalidateCssVarCache(theme?: string): void {
  cache.clear()
  cachedTheme = theme ?? null
}

/**
 * 读一个 CSS 变量的实际值。读不到时返回 fallback。
 *
 * @param name  变量名（含 `--`）
 * @param fallback 兜底色值
 */
export function cssVar(name: string, fallback: string): string {
  ensureThemeFresh()
  const hit = cache.get(name)
  if (hit) return hit
  if (typeof window === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  const value = raw || fallback
  cache.set(name, value)
  return value
}

/**
 * 给一个色值加透明度。
 *
 * CSS 变量里可能是 hex（`#ef4444`）也可能是 rgba（`rgba(59,130,246,0.08)`）。
 * hex 要转成 rgba 才能加透明度。
 */
export function withAlpha(color: string, alpha: number): string {
  if (color.startsWith('#')) {
    const h = color.slice(1)
    const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
    const r = parseInt(full.slice(0, 2), 16)
    const g = parseInt(full.slice(2, 4), 16)
    const b = parseInt(full.slice(4, 6), 16)
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
  }
  // 已经是 rgba/rgb —— 用正则替换 alpha
  return color.replace(/rgba?\(([^)]+)\)/, (_m, inner: string) => {
    const parts = inner.split(',').map((p) => p.trim())
    return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${alpha})`
  })
}

/**
 * 读一个颜色变量并附加透明度。
 */
export function cssVarAlpha(name: string, alpha: number, fallback: string): string {
  return withAlpha(cssVar(name, fallback), alpha)
}
