/**
 * 指标频率的格式校验。
 *
 * 与后端 `platform/timeutil.py::freq_delta` 的正则保持一致：
 * 先 `strip().lower()`，再匹配 `^(\d+)(s|min|m|h|d)$`。
 *
 * ⚠️ 这里只校验**格式**。频率是否与数据真实间隔一致，后端也不校验
 *    （那需要扫一遍数据才能知道），属于已知限制。
 */

const FREQ_PATTERN = /^(\d+)(s|min|m|h|d)$/

/** 常用示例，给表单占位与错误提示复用。 */
export const FREQ_EXAMPLES = ['1s', '1min', '5min', '1h', '1d'] as const

export function isValidFreq(value: string | null | undefined): boolean {
  const text = String(value ?? '').trim().toLowerCase()
  const match = FREQ_PATTERN.exec(text)
  // 数字必须为正 —— 后端 freq_delta 对 amount <= 0 也会拒绝
  return Boolean(match) && Number(match![1]) > 0
}

/** AntD Form.Item 的 validator：空值交给 `required` 规则，这里只判格式。 */
export function freqValidator(_rule: unknown, value: string | undefined): Promise<void> {
  if (!value || isValidFreq(value)) return Promise.resolve()
  return Promise.reject(
    new Error(`频率格式应为「数字 + 单位」，单位可选 s / min / m / h / d（如 5min、1h、1d）`),
  )
}
